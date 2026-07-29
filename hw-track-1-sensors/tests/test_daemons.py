"""Tests for heart rate daemon, anchor gesture detector, and worn detector."""
import sys, os
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from mock_hal.sensor_types import PPGReading, SensorStatus, UnavailableReason
from daemons.heart_rate_daemon import HeartRateDaemon, HRQuality
from daemons.anchor_gesture_detector import AnchorGestureDetector
from daemons.worn_detector import WornNotWornDetector, WornState


def make_ppg(t, hr=70.0, q=0.85, worn=True):
    if not worn:
        return PPGReading(timestamp=t, status=SensorStatus.NOT_WORN,
                          unavailable_reason=UnavailableReason.DEVICE_NOT_WORN)
    return PPGReading(timestamp=t, status=SensorStatus.OK,
                      heart_rate_bpm=hr, signal_quality=q, spo2_percent=98.0)


# ============ Heart Rate Daemon ============

class TestHeartRateDaemon:
    def setup_method(self):
        self.d = HeartRateDaemon()

    def test_good_quality_stable_hr(self):
        out = None
        for i in range(10):
            out = self.d.update(make_ppg(i * 0.1, hr=72, q=0.9))
        assert out.valid
        assert out.quality_label == HRQuality.GOOD
        assert out.trustworthy

    def test_rule3_not_worn(self):
        out = self.d.update(make_ppg(1.0, worn=False))
        assert not out.valid
        assert out.quality_label == HRQuality.UNAVAILABLE
        assert out.heart_rate_bpm is None
        assert out.trustworthy is False

    def test_low_sensor_quality_flagged(self):
        out = None
        for i in range(5):
            out = self.d.update(make_ppg(i * 0.1, hr=72, q=0.2))
        assert not out.trustworthy  # low quality must not be trusted

    def test_implausible_hr_not_trusted(self):
        out = self.d.update(make_ppg(1.0, hr=300, q=0.9))  # impossible HR
        assert not out.trustworthy

    def test_sudden_jump_lowers_quality(self):
        for i in range(10):
            self.d.update(make_ppg(i * 0.1, hr=70, q=0.9))
        # sudden jump to 140
        out = self.d.update(make_ppg(1.1, hr=140, q=0.9))
        # stability component should drag quality down
        assert out.signal_quality < 0.9


# ============ Anchor Gesture Detector — the critical distinction ============

class TestAnchorGestureDetector:
    def setup_method(self):
        self.a = AnchorGestureDetector()

    def test_opens_30s_window(self):
        sig = self.a.on_double_tap(100.0)
        assert sig.window.start == 85.0
        assert sig.window.end == 115.0
        assert self.a.active_window_count == 1

    def test_emits_moment_marked_signal(self):
        sig = self.a.on_double_tap(50.0)
        assert sig.message == "moment_marked"
        assert len(self.a.signals) == 1

    def test_CRITICAL_never_touches_capture_state(self):
        """
        The whole point: a double-tap is ONLY an annotation marker.
        This module has no capture-state attribute or method AT ALL —
        prove it structurally.
        """
        # The detector must not expose any capture-related interface
        forbidden = ['capture_level', 'set_level', 'trigger_camera',
                     'start_recording', 'camera_burst', 'capture_intensity']
        for attr in forbidden:
            assert not hasattr(self.a, attr), \
                f"anchor detector must NOT have '{attr}' — it only annotates"

    def test_CRITICAL_signal_carries_no_capture_command(self):
        """The emitted signal must not carry any capture instruction."""
        sig = self.a.on_double_tap(10.0)
        # signal only has timestamp, window, message — nothing capture-related
        sig_fields = vars(sig).keys()
        for f in sig_fields:
            assert 'level' not in f.lower()
            assert 'camera' not in f.lower()
            assert 'record' not in f.lower()
            assert 'capture' not in f.lower()

    def test_attach_note(self):
        self.a.on_double_tap(100.0)
        ok = self.a.attach_note(100.0, "great moment")
        assert ok
        assert self.a.windows[0].note == "great moment"

    def test_note_attaches_to_nearest(self):
        self.a.on_double_tap(50.0)
        self.a.on_double_tap(200.0)
        self.a.attach_note(205.0, "the second one")
        assert self.a.windows[1].note == "the second one"
        assert self.a.windows[0].note is None


# ============ Worn / Not-Worn Detector ============

class TestWornDetector:
    def setup_method(self):
        self.w = WornNotWornDetector()

    def test_starts_worn_with_good_signals(self):
        out = self.w.update(0.0, hr_quality=0.9,
                            orientation_variance=6.0, accel_activity=0.04)
        assert out.state == WornState.WORN
        assert out.vote_score >= 0.5

    def test_not_worn_requires_5min_continuous(self):
        """Must stay not-worn 5+ minutes before transitioning."""
        # bad signals but only for 4 minutes -> still worn
        for t in range(0, 240, 1):
            out = self.w.update(float(t), hr_quality=0.0,
                               orientation_variance=0.0, accel_activity=0.0)
        assert out.state == WornState.WORN  # not yet 5 min

    def test_transitions_to_not_worn_after_5min(self):
        out = None
        for t in range(0, 320, 1):
            out = self.w.update(float(t), hr_quality=0.0,
                               orientation_variance=0.0, accel_activity=0.0)
        assert out.state == WornState.NOT_WORN

    def test_gradual_wakeup_not_instant(self):
        """After not-worn, putting device back on triggers 15s gradual wake-up."""
        # get to not-worn
        for t in range(0, 320, 1):
            self.w.update(float(t), 0.0, 0.0, 0.0)
        assert self.w.state == WornState.NOT_WORN

        # put back on — should enter WAKING_UP, not jump straight to WORN
        out = self.w.update(321.0, hr_quality=0.9,
                           orientation_variance=6.0, accel_activity=0.04)
        assert out.state == WornState.WAKING_UP
        assert out.wakeup_progress is not None
        assert out.wakeup_progress < 1.0

        # 10 seconds in — still waking up
        out = self.w.update(331.0, 0.9, 6.0, 0.04)
        assert out.state == WornState.WAKING_UP

        # 15+ seconds in — now fully worn
        out = self.w.update(337.0, 0.9, 6.0, 0.04)
        assert out.state == WornState.WORN

    def test_hr_quality_dominates_vote(self):
        """HR quality has highest weight (0.55)."""
        # only HR good, everything else zero
        out = self.w.update(0.0, hr_quality=1.0,
                           orientation_variance=0.0, accel_activity=0.0)
        # 0.55 * 1.0 = 0.55 >= threshold
        assert out.vote_score >= 0.5
        assert out.state == WornState.WORN


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
