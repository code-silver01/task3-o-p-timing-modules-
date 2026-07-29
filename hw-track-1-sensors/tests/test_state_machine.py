"""Tests for capture daemons (Rule 1) and the 6-level state machine."""
import sys, os
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from mock_hal.sensor_types import (
    CameraReading, AudioReading, SensorStatus, RawPayload, EncryptedPayload,
)
from mock_hal.mock_storage import MockStorage, EncryptionBypassAttempt
from daemons.capture_daemons import (
    CameraDaemon, AudioDaemon, StubEncryptionDaemon,
)
from state_machine.capture_state_machine import (
    CaptureStateMachine, CaptureSignals, Level,
)


# ============ Rule 1: capture daemons must encrypt before storage ============

class TestCaptureDaemonsRule1:
    def setup_method(self):
        self.enc = StubEncryptionDaemon()
        self.storage = MockStorage()

    def test_camera_encrypts_before_store(self):
        cam = CameraDaemon(self.enc, self.storage)
        frame = CameraReading(timestamp=1.0, status=SensorStatus.OK,
                              frame_id=1, width=1920, height=1080,
                              compression_level="moderate")
        assert cam.capture_and_store(frame)
        assert cam.frames_stored == 1
        # what's in storage must be an EncryptedPayload
        rec = self.storage.read("/vault/2026-07-12/camera/frame_000001")
        assert isinstance(rec, EncryptedPayload)

    def test_camera_skips_unavailable_frame(self):
        cam = CameraDaemon(self.enc, self.storage)
        bad = CameraReading(timestamp=1.0, status=SensorStatus.UNAVAILABLE)
        assert not cam.capture_and_store(bad)
        assert cam.frames_stored == 0

    def test_audio_L0_buffer_only_never_stored(self):
        """L0 audio is ring-buffer only — must NOT be written to disk."""
        aud = AudioDaemon(self.enc, self.storage)
        chunk = AudioReading(timestamp=1.0, status=SensorStatus.OK,
                             energy_rms=0.1, sample_rate_hz=8000)
        aud.capture_and_store(chunk, level="L0")
        assert aud.chunks_stored == 0
        assert aud.chunks_buffered_only == 1
        assert self.storage.write_count == 0

    def test_audio_L2_is_stored_encrypted(self):
        aud = AudioDaemon(self.enc, self.storage)
        chunk = AudioReading(timestamp=1.0, status=SensorStatus.OK,
                             energy_rms=0.3, sample_rate_hz=16000)
        assert aud.capture_and_store(chunk, level="L2")
        assert aud.chunks_stored == 1

    def test_storage_rejects_raw_from_any_daemon(self):
        """Even if a daemon tried to bypass encryption, storage refuses."""
        raw = RawPayload(data=b"sneaky", source_daemon="camera", timestamp=1.0)
        with pytest.raises(EncryptionBypassAttempt):
            self.storage.write("/vault/sneaky", raw)


# ============ 6-Level State Machine ============

def base_signals(t=0.0, **kw):
    """Quiet baseline signals (would sit at L0/L1)."""
    defaults = dict(
        timestamp=t, worn=True, upright=True, asleep=False,
        hr_quality=0.8, heart_rate=68.0, hr_baseline=68.0,
        motion_state="still", speech_fraction=0.0, num_speakers=0,
        voice_energy=0.05, voice_energy_baseline=0.1, hour_of_day=3,
    )
    defaults.update(kw)
    return CaptureSignals(**defaults)


class TestStateMachineTransitions:
    def setup_method(self):
        self.sm = CaptureStateMachine()

    def test_starts_at_L0(self):
        assert self.sm.level == Level.L0

    def test_L0_exit_requires_worn_upright(self):
        # not worn -> stay at L0
        self.sm.tick(base_signals(worn=False))
        assert self.sm.level == Level.L0
        # worn + upright + hr quality -> L1
        self.sm.tick(base_signals(worn=True, upright=True, hr_quality=0.8))
        assert self.sm.level == Level.L1

    def test_L1_to_L2_on_motion(self):
        self.sm.tick(base_signals())  # -> L1
        self.sm.tick(base_signals(motion_state="walking"))
        assert self.sm.level == Level.L2

    def test_L1_to_L2_on_time_of_day(self):
        self.sm.tick(base_signals())  # L1
        self.sm.tick(base_signals(hour_of_day=14))  # daytime
        assert self.sm.level == Level.L2

    def test_climb_to_L3_on_high_hr(self):
        self.sm.tick(base_signals(hour_of_day=14))  # L1
        self.sm.tick(base_signals(hour_of_day=14))  # L2
        self.sm.tick(base_signals(heart_rate=80, hr_baseline=68))  # +17% -> L3
        assert self.sm.level == Level.L3

    def test_L4_requires_all_three_conditions(self):
        # get to L3 first
        for _ in range(3):
            self.sm.tick(base_signals(hour_of_day=14, heart_rate=80))
        assert self.sm.level == Level.L3
        # L4 needs speech>40% AND >1 speaker AND arousal
        self.sm.tick(base_signals(hour_of_day=14, heart_rate=85,
                                  speech_fraction=0.5, num_speakers=2,
                                  voice_energy=0.5, voice_energy_baseline=0.1))
        assert self.sm.level == Level.L4

    def test_L4_not_reached_with_partial_conditions(self):
        for _ in range(3):
            self.sm.tick(base_signals(hour_of_day=14, heart_rate=80))
        assert self.sm.level == Level.L3
        # only speech, no multi-speaker -> should NOT reach L4
        self.sm.tick(base_signals(hour_of_day=14, heart_rate=85,
                                  speech_fraction=0.5, num_speakers=1))
        assert self.sm.level == Level.L3

    def test_L5_requires_3_of_6(self):
        # climb to L4
        for _ in range(3):
            self.sm.tick(base_signals(hour_of_day=14, heart_rate=80))
        self.sm.tick(base_signals(hour_of_day=14, heart_rate=85,
                                  speech_fraction=0.5, num_speakers=2,
                                  voice_energy=0.5, voice_energy_baseline=0.1))
        assert self.sm.level == Level.L4
        # L5: voice far above avg + HR 30%+ + >2 speakers overlapping = 3 conditions
        self.sm.tick(base_signals(hour_of_day=14, heart_rate=95,  # +40%
                                  speech_fraction=0.6, num_speakers=3,
                                  overlapping_speech=True,
                                  voice_energy=0.5, voice_energy_baseline=0.1))
        assert self.sm.level == Level.L5

    def test_config_matches_level(self):
        cfg = self.sm.current_config()
        assert cfg["name"] == "Dormant"
        assert cfg["camera_fps"] == 0


class TestStateMachineHysteresis:
    def setup_method(self):
        self.sm = CaptureStateMachine()

    def _climb_to_L5(self):
        for _ in range(3):
            self.sm.tick(base_signals(hour_of_day=14, heart_rate=80))
        self.sm.tick(base_signals(hour_of_day=14, heart_rate=85,
                                  speech_fraction=0.5, num_speakers=2,
                                  voice_energy=0.5, voice_energy_baseline=0.1))
        self.sm.tick(base_signals(hour_of_day=14, heart_rate=95,
                                  speech_fraction=0.6, num_speakers=3,
                                  overlapping_speech=True,
                                  voice_energy=0.5, voice_energy_baseline=0.1))
        assert self.sm.level == Level.L5

    def test_L5_holds_before_hysteresis_expires(self):
        self._climb_to_L5()
        t = self.sm.level  # L5
        # quiet signals but only 30s passed (< 45s hold)
        self.sm.tick(base_signals(timestamp=100.0, hour_of_day=14))
        self.sm.tick(base_signals(timestamp=130.0, hour_of_day=14))
        assert self.sm.level == Level.L5  # still holding

    def test_L5_steps_down_after_45s(self):
        self._climb_to_L5()
        # quiet for 46s
        self.sm.tick(base_signals(timestamp=200.0, hour_of_day=14))
        self.sm.tick(base_signals(timestamp=247.0, hour_of_day=14))
        assert self.sm.level == Level.L4

    def test_no_flicker_condition_reappears_resets_timer(self):
        self._climb_to_L5()
        # quiet 30s
        self.sm.tick(base_signals(timestamp=200.0, hour_of_day=14))
        # condition reappears at 230s (resets timer)
        self.sm.tick(base_signals(timestamp=230.0, hour_of_day=14,
                                  heart_rate=95, num_speakers=3,
                                  overlapping_speech=True,
                                  voice_energy=0.5, voice_energy_baseline=0.1))
        # quiet again, only 30s more (timer was reset, shouldn't drop yet)
        self.sm.tick(base_signals(timestamp=260.0, hour_of_day=14))
        assert self.sm.level == Level.L5

    def test_restart_at_L1_after_wakeup(self):
        """
        Spec: after the 15s wake-up, the state machine restarts at L1 —
        it must NOT snap back to the pre-removal level.
        """
        self._climb_to_L5()
        assert self.sm.level == Level.L5
        self.sm.restart_at_L1(timestamp=500.0)
        assert self.sm.level == Level.L1
        # transition is logged with its cause
        assert "restart at L1" in self.sm.transitions[-1].cause


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
