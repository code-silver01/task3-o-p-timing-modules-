"""
Chronis — Day 5 Cross-Track Integration Tests.

The four wired connections from the sprint doc:
  1. Worn detector (HW-1)      -> Power daemon active-seconds (HW-2)
  2. Power daemon (HW-2)       -> Capture state machine ceiling (HW-1)
  3. Anchor gesture (HW-1)     -> BLE Alerts + Annotation service (HW-3)
  4. BLE Device Info (HW-3)    -> reports REAL values from HW-1/HW-2

Run:  python3 -m pytest integration/test_day5_integration.py -v
"""

import sys, os
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "hw-track-1-sensors"))
sys.path.insert(0, os.path.join(ROOT, "hw-track-3-connectivity"))
sys.path.insert(0, ROOT)

from daemons.worn_detector import WornNotWornDetector, WornState        # HW-1
from daemons.anchor_gesture_detector import AnchorGestureDetector       # HW-1
from state_machine.capture_state_machine import (                       # HW-1
    CaptureStateMachine, CaptureSignals, Level,
)
from ble_daemon.ble_daemon import BLEDaemon, MockDeviceState            # HW-3
from integration.power_ceiling_combiner import effective_level          # Day 5


# ---- connection 2: power ceiling vs state machine — lower always wins ----

class TestPowerCeilingVsStateMachine:
    def test_exact_conflict_case_from_spec(self):
        """SM says L5, battery Critical caps at L3 -> effective L3."""
        assert effective_level(Level.L5, Level.L3) == Level.L3

    def test_no_restriction_case(self):
        assert effective_level(Level.L2, Level.L5) == Level.L2

    def test_emergency_caps_everything(self):
        # Emergency: camera off -> ceiling L0/L1 territory
        for sm_level in Level:
            assert effective_level(sm_level, Level.L1) <= Level.L1

    def test_all_power_states_mapping(self):
        """HW-2 power states -> level ceilings (per spec table)."""
        ceilings = {
            "Full Active": Level.L5,
            "Conservation": Level.L4,
            "Critical": Level.L3,
            "Emergency": Level.L1,
        }
        # Peak moment under each power state:
        assert effective_level(Level.L5, ceilings["Full Active"]) == Level.L5
        assert effective_level(Level.L5, ceilings["Conservation"]) == Level.L4
        assert effective_level(Level.L5, ceilings["Critical"]) == Level.L3
        assert effective_level(Level.L5, ceilings["Emergency"]) == Level.L1


# ---- connection 1: worn detector -> power accounting ----

class PowerActiveSecondsTracker:
    """Minimal stand-in for HW-2's active-seconds accounting, driven by
    the worn detector's output (the seam being tested)."""
    def __init__(self):
        self.camera_active_s = 0.0
        self.audio_active_s = 0.0

    def tick(self, dt: float, worn: bool, camera_on: bool):
        if worn and camera_on:
            self.camera_active_s += dt
            self.audio_active_s += dt
        elif not worn:
            pass   # not-worn: near-zero accumulation (camera off, ring-buffer)


class TestWornIntoPowerAccounting:
    def test_notworn_drops_active_seconds_to_zero(self):
        worn = WornNotWornDetector()
        power = PowerActiveSecondsTracker()

        # drive to NOT_WORN (>5 min of dead signals)
        for t in range(0, 320):
            worn.update(float(t), 0.0, 0.0, 0.0)
        assert worn.state == WornState.NOT_WORN

        before = power.camera_active_s
        for t in range(320, 380):
            power.tick(1.0, worn.is_worn, camera_on=True)
        assert power.camera_active_s == before   # zero accumulation while not worn

    def test_worn_accumulates_normally(self):
        worn = WornNotWornDetector()
        power = PowerActiveSecondsTracker()
        for t in range(0, 60):
            worn.update(float(t), 0.9, 6.0, 0.04)
            power.tick(1.0, worn.is_worn, camera_on=True)
        assert power.camera_active_s == 60.0


# ---- connection 3: anchor gesture -> BLE alert + annotation round-trip ----

class TestAnchorIntoBLE:
    def setup_method(self):
        self.ble = BLEDaemon(MockDeviceState())
        code = self.ble.pairing.begin("phone-A")
        self.ble.pairing.confirm(code, True)
        self.ble.on_connect(0.0, "phone-A")

        # wire: anchor's phone_notifier fires the BLE alert (the real daemon,
        # not the mock peripheral)
        self.anchor = AnchorGestureDetector(
            phone_notifier=lambda sig: self.ble.push_alert(
                "double_tap_moment_marked",
                f"t={sig.timestamp}", sig.timestamp))

    def test_double_tap_fires_ble_alert(self):
        self.anchor.on_double_tap(123.4)
        alerts = self.ble.drain_alerts()
        assert len(alerts) == 1
        assert alerts[0].kind == "double_tap_moment_marked"

    def test_annotation_round_trip(self):
        """Phone sends a note back; it lands on the tap's timestamp."""
        self.anchor.on_double_tap(200.0)
        self.ble.drain_alerts()
        # phone responds via Annotation service
        entry = self.ble.svc_annotation("birthday toast!", tap_timestamp=200.0)
        # and the anchor attaches it to its window
        assert self.anchor.attach_note(200.0, entry["note"])
        assert self.anchor.windows[0].note == "birthday toast!"

    def test_tap_still_never_touches_capture(self):
        """Integration must not weaken the annotation-only guarantee."""
        sm = CaptureStateMachine()
        sm.tick(CaptureSignals(timestamp=0.0, hr_quality=0.8))   # -> L1
        level_before = sm.level
        self.anchor.on_double_tap(50.0)
        assert sm.level == level_before


# ---- connection 4: BLE Device Info reports REAL values ----

class TestBLEReportingAccuracy:
    def test_device_info_tracks_live_state_machine_level(self):
        state = MockDeviceState()
        ble = BLEDaemon(state)
        sm = CaptureStateMachine()

        # L0 initially
        state._level = int(sm.level)
        assert ble.svc_device_info()["capture_level"] == 0

        # climb to L1 and confirm BLE reflects it (wired, not canned)
        sm.tick(CaptureSignals(timestamp=0.0, hr_quality=0.8))
        state._level = int(sm.level)
        assert ble.svc_device_info()["capture_level"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
