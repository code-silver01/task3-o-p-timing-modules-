import sys, os
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from voice_wake.voice_gate import VoiceGate, NotEnrolledError
from oled.mock_display_buffer import MockDisplayBuffer
from oled.oled_controller import OLEDDisplayManager

# Two clearly-separated synthetic "voice fingerprints" — stand-ins for
# what a real embedding model would output. They just need to be
# consistently far apart from each other and consistently close to their
# own noisy variants, which is all the gate logic actually depends on.
ENROLLED_VOICE = [1.0, 0.0, 0.0, 0.0]
ENROLLED_VOICE_NOISY_REPEAT = [0.95, 0.05, -0.02, 0.01]   # same person, slightly different take
OTHER_VOICE = [0.0, 1.0, 0.0, 0.0]


class TestEnrollmentGating:
    def test_checking_before_enrollment_raises(self):
        gate = VoiceGate()
        with pytest.raises(NotEnrolledError):
            gate.matches_enrolled_voice(OTHER_VOICE)

    def test_is_enrolled_reflects_state(self):
        gate = VoiceGate()
        assert gate.is_enrolled is False
        gate.enroll(ENROLLED_VOICE)
        assert gate.is_enrolled is True


class TestVoiceMatching:
    def test_enrolled_voice_matches(self):
        gate = VoiceGate()
        gate.enroll(ENROLLED_VOICE)
        assert gate.matches_enrolled_voice(ENROLLED_VOICE) is True

    def test_noisy_repeat_of_enrolled_voice_still_matches(self):
        gate = VoiceGate()
        gate.enroll(ENROLLED_VOICE)
        assert gate.matches_enrolled_voice(ENROLLED_VOICE_NOISY_REPEAT) is True

    def test_other_voice_does_not_match(self):
        gate = VoiceGate()
        gate.enroll(ENROLLED_VOICE)
        assert gate.matches_enrolled_voice(OTHER_VOICE) is False


class TestWakeTrigger:
    """The spec's literal ask: enrolled voice triggers the display,
    other voice does not."""

    def test_enrolled_voice_wakes_the_display(self):
        gate = VoiceGate()
        gate.enroll(ENROLLED_VOICE)
        display = OLEDDisplayManager(MockDisplayBuffer())
        assert display.buffer.snapshot()["content"]["mode"] == "ambient"

        woke = gate.trigger_wake(ENROLLED_VOICE, display_manager=display)

        assert woke is True
        snap = display.buffer.snapshot()
        assert snap["content"].get("mode") != "ambient"   # display actually woke

    def test_other_voice_does_not_wake_the_display(self):
        gate = VoiceGate()
        gate.enroll(ENROLLED_VOICE)
        display = OLEDDisplayManager(MockDisplayBuffer())

        woke = gate.trigger_wake(OTHER_VOICE, display_manager=display)

        assert woke is False
        # display must still be in ambient mode — nothing happened
        assert display.buffer.snapshot()["content"]["mode"] == "ambient"