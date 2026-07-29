"""
Power Management Daemon (Day 3).
Answers: does the device correctly change its own behavior in real time as the battery drains?
NOT a battery-life projection — that is power_thermal_estimate.py.

Four power states layered as restrictions ON TOP of HW-1's capture-intensity state machine.
The daemon caps; it does not replace the state machine's decision.
Boundary values per spec: 40% (Full→Conservation), 20% (Conservation→Critical), 5% (Critical→Emergency).
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Dict, List, Optional


# ── Lithium discharge curve (voltage → percent), generic stand-in ─────────────
# Voltage values are from a generic 3.7V nominal LiPo cell.
_DISCHARGE_CURVE: List[tuple[float, float]] = [
    (4.20, 100.0),
    (4.10, 90.0),
    (4.00, 80.0),
    (3.90, 70.0),
    (3.80, 60.0),
    (3.70, 50.0),
    (3.60, 40.0),
    (3.50, 30.0),
    (3.40, 20.0),
    (3.30, 10.0),
    (3.20, 5.0),
    (3.10, 2.0),
    (3.00, 0.0),
]


def voltage_to_percent(voltage: float) -> float:
    """Convert ADC voltage reading to battery percentage via lookup table interpolation."""
    if voltage >= _DISCHARGE_CURVE[0][0]:
        return 100.0
    if voltage <= _DISCHARGE_CURVE[-1][0]:
        return 0.0
    for i in range(len(_DISCHARGE_CURVE) - 1):
        v_hi, pct_hi = _DISCHARGE_CURVE[i]
        v_lo, pct_lo = _DISCHARGE_CURVE[i + 1]
        if v_lo <= voltage <= v_hi:
            ratio = (voltage - v_lo) / (v_hi - v_lo)
            return pct_lo + ratio * (pct_hi - pct_lo)
    return 0.0


# ── Power states ──────────────────────────────────────────────────────────────

class PowerState(Enum):
    FULL_ACTIVE = "full_active"        # > 40%
    CONSERVATION = "conservation"      # 20–40%
    CRITICAL = "critical"              # < 20%
    EMERGENCY = "emergency"            # < 5%
    CHARGING = "charging"              # charging current detected


def _state_for_percent(pct: float) -> PowerState:
    if pct < 5.0:
        return PowerState.EMERGENCY
    if pct < 20.0:
        return PowerState.CRITICAL
    if pct <= 40.0:
        return PowerState.CONSERVATION
    return PowerState.FULL_ACTIVE


@dataclass
class PowerRestrictions:
    camera_max_level: Optional[int]   # None = off
    led_max_brightness_pct: int
    audio_max_level: Optional[int]    # None = ring-buffer only
    sync_enabled: bool
    wifi_enabled: bool
    ble_beacon_only: bool
    motion_hr_minimum_sampling: bool


_RESTRICTIONS: Dict[PowerState, PowerRestrictions] = {
    PowerState.FULL_ACTIVE: PowerRestrictions(
        camera_max_level=5,
        led_max_brightness_pct=100,
        audio_max_level=5,
        sync_enabled=True,
        wifi_enabled=True,
        ble_beacon_only=False,
        motion_hr_minimum_sampling=False,
    ),
    PowerState.CONSERVATION: PowerRestrictions(
        camera_max_level=4,
        led_max_brightness_pct=50,
        audio_max_level=4,
        sync_enabled=True,      # throttled per spec, but not disabled
        wifi_enabled=True,
        ble_beacon_only=False,
        motion_hr_minimum_sampling=False,
    ),
    PowerState.CRITICAL: PowerRestrictions(
        camera_max_level=3,
        led_max_brightness_pct=20,
        audio_max_level=3,
        sync_enabled=False,
        wifi_enabled=True,
        ble_beacon_only=False,
        motion_hr_minimum_sampling=False,
    ),
    PowerState.EMERGENCY: PowerRestrictions(
        camera_max_level=None,  # camera off
        led_max_brightness_pct=5,   # low-battery pulse only
        audio_max_level=None,   # ring-buffer only, not saved
        sync_enabled=False,
        wifi_enabled=False,
        ble_beacon_only=True,
        motion_hr_minimum_sampling=True,
    ),
    PowerState.CHARGING: PowerRestrictions(
        camera_max_level=5,
        led_max_brightness_pct=100,
        audio_max_level=5,
        sync_enabled=True,
        wifi_enabled=True,
        ble_beacon_only=False,
        motion_hr_minimum_sampling=False,
    ),
}


# ── Daily power report schema ─────────────────────────────────────────────────

@dataclass
class SubsystemSeconds:
    camera: float = 0.0
    audio: float = 0.0
    motion: float = 0.0
    heart_rate: float = 0.0
    ble: float = 0.0
    wifi: float = 0.0


@dataclass
class DailyPowerReport:
    date: str
    active_seconds: SubsystemSeconds
    partial_charge_cycles: float
    estimated_power_consumed_mwh: float
    time_at_state: Dict[str, float]   # PowerState.value → seconds

    def to_json(self) -> str:
        return json.dumps({
            "date": self.date,
            "active_seconds": {
                "camera": self.active_seconds.camera,
                "audio": self.active_seconds.audio,
                "motion": self.active_seconds.motion,
                "heart_rate": self.active_seconds.heart_rate,
                "ble": self.active_seconds.ble,
                "wifi": self.active_seconds.wifi,
            },
            "partial_charge_cycles": self.partial_charge_cycles,
            "estimated_power_consumed_mwh": self.estimated_power_consumed_mwh,
            "time_at_state_seconds": self.time_at_state,
        }, indent=2)


# ── Daemon ────────────────────────────────────────────────────────────────────

class PowerManagementDaemon:
    """
    Real-time battery-state logic. Reads mock ADC voltage; enforces restriction caps.
    """

    def __init__(
        self,
        adc_read_fn: Callable[[], float],
        charging_detected_fn: Callable[[], bool],
        notify_phone_fn: Callable[[str], None],
        log_fn: Callable[[str], None],
    ):
        self._adc_read = adc_read_fn
        self._charging_detected = charging_detected_fn
        self._notify = notify_phone_fn
        self._log = log_fn
        self._current_state: Optional[PowerState] = None
        self._conservation_notified = False

    def tick(self) -> PowerState:
        """
        Called periodically. Reads battery, updates state, fires notifications on state entry.
        Returns the current PowerState.
        """
        if self._charging_detected():
            new_state = PowerState.CHARGING
        else:
            voltage = self._adc_read()
            if voltage is None:
                # Rule 3: explicit unavailable — log it, don't substitute a zero
                self._log("ADC read returned unavailable — cannot determine battery state.")
                return self._current_state or PowerState.FULL_ACTIVE
            pct = voltage_to_percent(voltage)
            new_state = _state_for_percent(pct)

        self._apply_state_transition(new_state)
        self._current_state = new_state
        return new_state

    def get_restrictions(self) -> PowerRestrictions:
        state = self._current_state or PowerState.FULL_ACTIVE
        return _RESTRICTIONS[state]

    def get_battery_percent(self) -> Optional[float]:
        voltage = self._adc_read()
        if voltage is None:
            return None
        return voltage_to_percent(voltage)

    def _apply_state_transition(self, new_state: PowerState) -> None:
        if new_state == self._current_state:
            return

        if new_state == PowerState.CONSERVATION and not self._conservation_notified:
            self._notify("Battery at Conservation mode (20–40%) — some features capped.")
            self._conservation_notified = True

        elif new_state == PowerState.CRITICAL:
            self._notify("ALERT: Battery Critical (below 20%) — sync disabled.")
            self._conservation_notified = False  # reset for next entry into conservation

        elif new_state == PowerState.EMERGENCY:
            self._notify("URGENT: Battery Emergency (below 5%) — minimal operation only.")

        elif new_state == PowerState.CHARGING:
            self._log("Charging detected — charging animation active.")
            self._conservation_notified = False

        self._log(f"Power state: {self._current_state} → {new_state}")

    @property
    def current_state(self) -> Optional[PowerState]:
        return self._current_state

    def generate_daily_report(
        self,
        date_str: str,
        active_seconds: SubsystemSeconds,
        partial_cycles: float,
        power_consumed_mwh: float,
        time_at_state: Dict[str, float],
    ) -> DailyPowerReport:
        return DailyPowerReport(
            date=date_str,
            active_seconds=active_seconds,
            partial_charge_cycles=partial_cycles,
            estimated_power_consumed_mwh=power_consumed_mwh,
            time_at_state=time_at_state,
        )
