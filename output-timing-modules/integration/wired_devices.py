"""
Chronis Task 3, Team B, Day 4 — Wired Output Devices.

This is the literal "wire LED, OLED, and NTP into the existing mock HAL
alongside every daemon from Tasks 1 and 2" instruction. It doesn't import
anything from Task 1 directly — the caller (which already has Task 1's
code on its path, per this repo's existing convention) computes the
values and passes them in as plain types (int, bool). That keeps this
module reusable without hardcoding a dependency on Task 1's exact import
path, the same design choice Team B's Day 4 of Task 2 made with
telemetry/checks.py taking `hal`/`storage` as plain arguments.
"""

from led.led_controller import LEDController
from led.led_states import LEDState
from oled.oled_controller import OLEDDisplayManager
from oled.oled_states import DisplayState
from ntp_sync.ntp_daemon import NTPSyncDaemon
from ntp_sync.mock_time_source import MockNTPTimeSource
from ntp_sync.drift_log import DriftLog
from voice_wake.voice_gate import VoiceGate


class WiredOutputDevices:
    def __init__(self, led_driver, display_buffer, drift_log_path: str):
        self.led = LEDController(led_driver)
        self.oled = OLEDDisplayManager(display_buffer)
        self.ntp = NTPSyncDaemon(MockNTPTimeSource(), DriftLog(drift_log_path))
        self.voice_gate = VoiceGate()

    def on_cse_tick(self, level_int: int, capturing: bool, worn: bool):
        """
        Call this once per 500ms CSE tick — the exact cadence Task 1's own
        driver (state_machine/extended_run.py) calls
        CaptureStateMachine.tick() at. This is the "alongside every
        daemon" wiring: every time the CSE recalculates, the outputs
        recalculate too, on the same clock.

        level_int: the CSE's current level as a plain int, 0-5
        capturing: whether this level actually captures anything — Task 1's
                   own LEVEL_CONFIG[level]["audio_saved"] answers this;
                   L0 is False, L1-L5 are True. Reusing Task 1's own
                   definition here instead of inventing a new threshold.
        worn: the worn detector's current is_worn value
        """
        # ---- LED ----
        if not worn:
            self.led.trigger(LEDState.NOT_WORN_BREATHING_AMBER)
        else:
            # Day 1's own method already implements "dim dot at L4-L5, no
            # LED at all at L3 and below" — just feed it the real level.
            self.led.update_capture_indicator(level_int)

        # ---- OLED ----
        if capturing:
            self.oled.request(DisplayState.CAPTURE_ACTIVE_INDICATOR)
        else:
            self.oled.clear(DisplayState.CAPTURE_ACTIVE_INDICATOR)