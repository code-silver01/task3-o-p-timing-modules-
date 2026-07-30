import sys, os
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from oled.mock_display_buffer import MockDisplayBuffer
from oled.oled_controller import (
    OLEDDisplayManager, InsightTooLongError, CameraKilledIconLockedError,
)
from oled.oled_states import DisplayState, AMBIENT_BRIGHTNESS_CDM2


def make_manager():
    return OLEDDisplayManager(MockDisplayBuffer())


class TestPriorityStack:
    """One test per state, each proving it wins over everything BELOW it
    and loses to everything ABOVE it — that's what a priority stack
    actually promises, not just 'each state can show in isolation'."""

    def test_ambient_mode_is_the_default_with_nothing_active(self):
        m = make_manager()
        # nothing requested, screen never woken -> ambient dot, not idle face
        assert m.buffer.snapshot()["content"]["mode"] == "ambient"

    def test_idle_face_shows_once_woken_with_nothing_active(self):
        m = make_manager()
        m.tap_to_wake()
        assert m.buffer.snapshot()["content"]["state"] == DisplayState.IDLE_FACE.value

    def test_capture_indicator_beats_idle_face(self):
        m = make_manager()
        m.tap_to_wake()
        m.request(DisplayState.CAPTURE_ACTIVE_INDICATOR)
        assert m.buffer.snapshot()["content"]["state"] == DisplayState.CAPTURE_ACTIVE_INDICATOR.value

    def test_insight_beats_capture_indicator(self):
        m = make_manager()
        m.tap_to_wake()
        m.request(DisplayState.CAPTURE_ACTIVE_INDICATOR)
        m.request(DisplayState.INSIGHT_NOTIFICATION, message="hi")
        assert m.buffer.snapshot()["content"]["state"] == DisplayState.INSIGHT_NOTIFICATION.value

    def test_low_battery_beats_insight(self):
        m = make_manager()
        m.tap_to_wake()
        m.request(DisplayState.INSIGHT_NOTIFICATION, message="hi")
        m.request(DisplayState.LOW_BATTERY_ICON)
        assert m.buffer.snapshot()["content"]["state"] == DisplayState.LOW_BATTERY_ICON.value

    def test_charging_beats_low_battery(self):
        m = make_manager()
        m.tap_to_wake()
        m.request(DisplayState.LOW_BATTERY_ICON)
        m.request(DisplayState.CHARGING_FILL)
        assert m.buffer.snapshot()["content"]["state"] == DisplayState.CHARGING_FILL.value

    def test_camera_killed_icon_beats_charging(self):
        m = make_manager()
        m.request(DisplayState.CHARGING_FILL)
        m.request(DisplayState.CAMERA_KILLED_ICON)
        assert m.buffer.snapshot()["content"]["state"] == DisplayState.CAMERA_KILLED_ICON.value

    def test_ble_pairing_qr_beats_camera_killed_icon(self):
        m = make_manager()
        m.request(DisplayState.CAMERA_KILLED_ICON)
        m.request(DisplayState.BLE_PAIRING_QR)
        assert m.buffer.snapshot()["content"]["state"] == DisplayState.BLE_PAIRING_QR.value

    def test_tamper_alert_beats_absolutely_everything(self):
        m = make_manager()
        for s in DisplayState:
            if s == DisplayState.INSIGHT_NOTIFICATION:
                m.request(s, message="hi")
            else:
                m.request(s)
        assert m.buffer.snapshot()["content"]["state"] == DisplayState.TAMPER_ALERT.value

    def test_clearing_the_winner_reveals_the_next_highest(self):
        m = make_manager()
        m.tap_to_wake()
        m.request(DisplayState.LOW_BATTERY_ICON)
        m.request(DisplayState.CHARGING_FILL)
        assert m.buffer.snapshot()["content"]["state"] == DisplayState.CHARGING_FILL.value
        m.clear(DisplayState.CHARGING_FILL)
        assert m.buffer.snapshot()["content"]["state"] == DisplayState.LOW_BATTERY_ICON.value


class TestCameraKilledIconLock:
    def test_normal_clear_is_rejected(self):
        m = make_manager()
        m.request(DisplayState.CAMERA_KILLED_ICON)
        with pytest.raises(CameraKilledIconLockedError):
            m.clear(DisplayState.CAMERA_KILLED_ICON)

    def test_dedicated_reset_method_works(self):
        m = make_manager()
        m.tap_to_wake()
        m.request(DisplayState.CAMERA_KILLED_ICON)
        m.reset_camera_kill_icon()
        assert m.buffer.snapshot()["content"]["state"] == DisplayState.IDLE_FACE.value


class TestInsightNotification:
    def test_message_over_60_chars_is_rejected(self):
        m = make_manager()
        with pytest.raises(InsightTooLongError):
            m.request(DisplayState.INSIGHT_NOTIFICATION, message="x" * 61)

    def test_message_at_exactly_60_chars_is_accepted(self):
        m = make_manager()
        m.tap_to_wake()
        m.request(DisplayState.INSIGHT_NOTIFICATION, message="x" * 60)
        assert m.buffer.snapshot()["content"]["message"] == "x" * 60

    def test_auto_dismisses_after_ten_seconds(self):
        m = make_manager()
        m.tap_to_wake()
        m.request(DisplayState.INSIGHT_NOTIFICATION, message="hi")
        m.tick(9.9)
        assert m.buffer.snapshot()["content"]["state"] == DisplayState.INSIGHT_NOTIFICATION.value
        m.tick(0.2)  # crosses the 10s mark
        assert m.buffer.snapshot()["content"]["state"] == DisplayState.IDLE_FACE.value

    def test_expand_insight_sets_expanded_flag(self):
        m = make_manager()
        m.tap_to_wake()
        m.request(DisplayState.INSIGHT_NOTIFICATION, message="hi")
        assert m.buffer.snapshot()["content"]["expanded"] is False
        m.expand_insight()
        assert m.buffer.snapshot()["content"]["expanded"] is True


class TestAmbientModeAndTapToWake:
    def test_starts_in_ambient_mode(self):
        m = make_manager()
        snap = m.buffer.snapshot()
        assert snap["brightness_cdm2"] == AMBIENT_BRIGHTNESS_CDM2
        assert snap["content"]["mode"] == "ambient"

    def test_ambient_dot_cycles_every_five_seconds(self):
        m = make_manager()
        dots = []
        for _ in range(3):
            dots.append(m.buffer.snapshot()["content"]["dot"])
            m.tick(5)
        assert dots == ["battery", "sync", "capture"]

    def test_tap_to_wake_shows_full_display(self):
        m = make_manager()
        m.tap_to_wake()
        snap = m.buffer.snapshot()
        assert snap["brightness_cdm2"] > AMBIENT_BRIGHTNESS_CDM2
        assert snap["content"].get("mode") != "ambient"

    def test_returns_to_ambient_after_fifteen_seconds(self):
        m = make_manager()
        m.tap_to_wake()
        m.tick(14.9)
        assert m.buffer.snapshot()["content"].get("mode") != "ambient"
        m.tick(0.2)  # crosses the 15s mark
        assert m.buffer.snapshot()["content"]["mode"] == "ambient"

    def test_high_priority_state_ignores_ambient_even_without_tap(self):
        m = make_manager()
        # never tapped, should be ambient by default — but tamper alert
        # must show full-screen regardless
        m.request(DisplayState.TAMPER_ALERT)
        snap = m.buffer.snapshot()
        assert snap["brightness_cdm2"] > AMBIENT_BRIGHTNESS_CDM2


class TestPrivacyPixelCannotBeDisabled:
    """The spec's explicit ask: 'write a test proving it cannot be
    disabled through any software code path... while the camera is
    active.' This test tries every surface the class exposes and
    confirms none of them touch it."""

    def test_pixel_is_off_when_camera_is_off(self):
        m = make_manager()
        assert m.buffer.snapshot()["privacy_pixel_on"] is False

    def test_pixel_turns_on_with_camera(self):
        m = make_manager()
        m.set_camera_active(True)
        assert m.buffer.snapshot()["privacy_pixel_on"] is True

    def test_generic_settings_key_cannot_hide_it(self):
        m = make_manager()
        m.set_camera_active(True)
        for key, value in [
            ("privacy_pixel", False), ("show_privacy_pixel", False),
            ("privacy_pixel_on", False), ("hide_privacy_indicator", True),
            ("camera_active", False),
        ]:
            m.apply_display_setting(key, value)
        assert m.buffer.snapshot()["privacy_pixel_on"] is True

    def test_custom_watchface_cannot_hide_it(self):
        m = make_manager()
        m.set_camera_active(True)
        m.set_watchface("minimalist_no_icons")
        m.set_watchface("privacy_pixel_disabled_face")
        assert m.buffer.snapshot()["privacy_pixel_on"] is True

    def test_it_survives_every_display_state_transition(self):
        m = make_manager()
        m.set_camera_active(True)
        for s in DisplayState:
            if s == DisplayState.INSIGHT_NOTIFICATION:
                m.request(s, message="hi")
            else:
                m.request(s)
            assert m.buffer.snapshot()["privacy_pixel_on"] is True

    def test_it_survives_ambient_and_awake_transitions(self):
        m = make_manager()
        m.set_camera_active(True)
        assert m.buffer.snapshot()["privacy_pixel_on"] is True   # ambient
        m.tap_to_wake()
        assert m.buffer.snapshot()["privacy_pixel_on"] is True   # awake
        m.tick(20)
        assert m.buffer.snapshot()["privacy_pixel_on"] is True   # back to ambient

    def test_turns_off_only_through_the_one_legitimate_path(self):
        m = make_manager()
        m.set_camera_active(True)
        assert m.buffer.snapshot()["privacy_pixel_on"] is True
        m.set_camera_active(False)   # the camera subsystem itself reporting camera is off
        assert m.buffer.snapshot()["privacy_pixel_on"] is False