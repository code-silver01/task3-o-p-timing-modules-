import sys, os
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from led.mock_led_driver import MockLEDDriver, NUM_FRONT, NUM_BACK
from led.led_controller import LEDController, CannotSuppressError
from led.led_states import LEDState, UNSUPPRESSIBLE


def make_controller():
    return LEDController(MockLEDDriver())


class TestEachState:
    """One test per named state — confirms triggering it produces a
    distinguishable, correct-looking pattern. Not testing exact pixel
    values (that's an animation-design decision, not a correctness
    property) — testing that the RIGHT ZONE lights up for the RIGHT
    state, which is the actual functional requirement."""

    def test_charging_fill_lights_front_ring(self):
        c = make_controller()
        c.trigger(LEDState.CHARGING_FILL)
        snap = c.driver.snapshot()
        assert all(v > 0 for v in snap["front"])

    def test_sync_chase_lights_one_front_led(self):
        c = make_controller()
        c.trigger(LEDState.SYNC_CHASE)
        snap = c.driver.snapshot()
        assert sum(1 for v in snap["front"] if v > 0) == 1

    def test_low_battery_pulse_lights_front_dimly(self):
        c = make_controller()
        c.trigger(LEDState.LOW_BATTERY_PULSE)
        snap = c.driver.snapshot()
        assert all(0 < v < 255 for v in snap["front"])

    def test_new_insight_flash_lights_full_front(self):
        c = make_controller()
        c.trigger(LEDState.NEW_INSIGHT_FLASH)
        snap = c.driver.snapshot()
        assert all(v == 255 for v in snap["front"])

    def test_not_worn_breathing_amber_lights_back_only(self):
        c = make_controller()
        c.trigger(LEDState.NOT_WORN_BREATHING_AMBER)
        snap = c.driver.snapshot()
        assert all(v > 0 for v in snap["back"])
        assert all(v == 0 for v in snap["front"])

    def test_kill_switch_confirmation_lights_both_zones(self):
        c = make_controller()
        c.trigger(LEDState.KILL_SWITCH_CONFIRMATION_FLASH)
        snap = c.driver.snapshot()
        assert all(v > 0 for v in snap["front"])
        assert all(v > 0 for v in snap["back"])

    def test_tamper_alert_lights_both_zones(self):
        c = make_controller()
        c.trigger(LEDState.TAMPER_ALERT_PULSE)
        snap = c.driver.snapshot()
        assert all(v > 0 for v in snap["front"])
        assert all(v > 0 for v in snap["back"])

    def test_ble_pairing_chase_lights_one_front_led(self):
        c = make_controller()
        c.trigger(LEDState.BLE_PAIRING_CHASE)
        snap = c.driver.snapshot()
        assert sum(1 for v in snap["front"] if v > 0) == 1

    def test_mode_change_confirmation_lights_front(self):
        c = make_controller()
        c.trigger(LEDState.MODE_CHANGE_CONFIRMATION_FLASH)
        snap = c.driver.snapshot()
        assert all(v > 0 for v in snap["front"])

    def test_capture_indicator_dim_dot_at_l4_and_l5(self):
        c = make_controller()
        for level in (4, 5):
            c.update_capture_indicator(level)
            snap = c.driver.snapshot()
            lit = [v for v in snap["front"] if v > 0]
            assert len(lit) == 1
            assert lit[0] < 255  # must be dim, not full bright

    def test_capture_indicator_off_at_l3_and_below(self):
        c = make_controller()
        for level in (3, 2, 1, 0):
            c.update_capture_indicator(level)
            snap = c.driver.snapshot()
            assert all(v == 0 for v in snap["front"])
            assert all(v == 0 for v in snap["back"])


class TestSuppressionRule:
    def test_suppressing_tamper_alert_is_rejected(self):
        c = make_controller()
        with pytest.raises(CannotSuppressError):
            c.suppress(LEDState.TAMPER_ALERT_PULSE)

    def test_suppressing_kill_switch_confirmation_is_rejected(self):
        c = make_controller()
        with pytest.raises(CannotSuppressError):
            c.suppress(LEDState.KILL_SWITCH_CONFIRMATION_FLASH)

    def test_a_normal_state_can_be_suppressed_and_stays_dark(self):
        c = make_controller()
        c.suppress(LEDState.NEW_INSIGHT_FLASH)
        c.trigger(LEDState.NEW_INSIGHT_FLASH)
        snap = c.driver.snapshot()
        assert all(v == 0 for v in snap["front"])

    def test_tamper_alert_still_shows_even_if_everything_else_suppressed(self):
        c = make_controller()
        for s in LEDState:
            if s not in UNSUPPRESSIBLE:
                c.suppress(s)
        c.trigger(LEDState.TAMPER_ALERT_PULSE)
        snap = c.driver.snapshot()
        assert all(v > 0 for v in snap["front"])


class TestSleepSchedule:
    def test_before_10pm_is_normal_brightness(self):
        c = make_controller()
        c.set_time(21)
        c.trigger(LEDState.NEW_INSIGHT_FLASH)
        assert all(v == 255 for v in c.driver.snapshot()["front"])

    def test_exactly_10pm_boundary_is_dimmed(self):
        c = make_controller()
        c.set_time(22)
        c.trigger(LEDState.NEW_INSIGHT_FLASH)
        vals = c.driver.snapshot()["front"]
        assert all(0 < v < 255 for v in vals)

    def test_exactly_11pm_boundary_is_full_off(self):
        c = make_controller()
        c.set_time(23)
        c.trigger(LEDState.NEW_INSIGHT_FLASH)
        assert all(v == 0 for v in c.driver.snapshot()["front"])

    def test_middle_of_night_is_full_off(self):
        c = make_controller()
        c.set_time(2)
        c.trigger(LEDState.NEW_INSIGHT_FLASH)
        assert all(v == 0 for v in c.driver.snapshot()["front"])

    def test_charging_overrides_night_schedule(self):
        c = make_controller()
        c.set_time(23)          # would normally be full off
        c.set_charging(True)
        c.trigger(LEDState.NEW_INSIGHT_FLASH)
        assert all(v == 255 for v in c.driver.snapshot()["front"])

    def test_tamper_alert_bypasses_night_schedule_even_without_charging(self):
        c = make_controller()
        c.set_time(2)            # deep in the "full off" window
        c.set_charging(False)
        c.trigger(LEDState.TAMPER_ALERT_PULSE)
        snap = c.driver.snapshot()
        assert all(v > 0 for v in snap["front"])
        assert all(v > 0 for v in snap["back"])
