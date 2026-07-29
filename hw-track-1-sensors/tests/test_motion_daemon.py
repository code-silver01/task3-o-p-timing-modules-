"""Tests for the motion daemon."""
import sys, os, math
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from mock_hal.sensor_types import IMUReading, SensorStatus, UnavailableReason
from daemons.motion_daemon import MotionDaemon, MotionState, Posture


def make_imu(t, ax=0, ay=0, az=1.0, gx=0, gy=0, gz=0):
    return IMUReading(timestamp=t, status=SensorStatus.OK,
                      accel_x=ax, accel_y=ay, accel_z=az,
                      gyro_x=gx, gyro_y=gy, gyro_z=gz)


class TestMotionDaemon:
    def setup_method(self):
        self.d = MotionDaemon(sample_rate_hz=20.0)

    def test_still_when_no_motion(self):
        out = None
        for i in range(40):
            out = self.d.update(make_imu(i * 0.05))
        assert out.motion_state == MotionState.STILL

    def test_active_when_high_variance(self):
        import random
        rng = random.Random(1)
        out = None
        for i in range(40):
            out = self.d.update(make_imu(i * 0.05,
                                         ax=rng.gauss(0, 0.5),
                                         ay=rng.gauss(0, 0.5),
                                         az=1.0 + rng.gauss(0, 0.5)))
        assert out.motion_state in (MotionState.WALKING, MotionState.ACTIVE)

    def test_posture_upright(self):
        out = None
        for i in range(10):
            out = self.d.update(make_imu(i * 0.05, ax=0, ay=0, az=1.0))
        assert out.posture == Posture.UPRIGHT

    def test_posture_lying(self):
        # gravity on x-axis = lying down
        out = None
        for i in range(10):
            out = self.d.update(make_imu(i * 0.05, ax=1.0, ay=0, az=0))
        assert out.posture == Posture.LYING

    def test_rule3_invalid_reading(self):
        bad = IMUReading(timestamp=1.0, status=SensorStatus.UNAVAILABLE,
                         unavailable_reason=UnavailableReason.I2C_TIMEOUT)
        out = self.d.update(bad)
        assert not out.valid
        assert out.motion_state == MotionState.UNAVAILABLE
        assert out.pitch_deg is None
        assert out.unavailable_reason == "I2C read timed out"

    def test_double_tap_within_300ms(self):
        """Two accel spikes 200ms apart should register a double-tap."""
        detected = False
        t = 0.0
        # baseline
        for i in range(20):
            self.d.update(make_imu(t)); t += 0.05
        # first tap at t, second at t+0.2
        r = self.d.update(make_imu(t, az=2.2)); t += 0.05  # spike
        for _ in range(3):
            self.d.update(make_imu(t)); t += 0.05
        # second tap ~0.2s after first
        out = self.d.update(make_imu(t, az=2.2))
        if out.double_tap:
            detected = True
        assert detected, "double-tap should be detected within 300ms window"

    def test_no_double_tap_when_too_far_apart(self):
        """Taps 1 second apart should NOT register as double-tap."""
        t = 0.0
        for i in range(20):
            self.d.update(make_imu(t)); t += 0.05
        self.d.update(make_imu(t, az=2.2)); t += 0.05
        # wait 1 full second
        for _ in range(20):
            self.d.update(make_imu(t)); t += 0.05
        out = self.d.update(make_imu(t, az=2.2))
        assert not out.double_tap

    def test_triple_tap_fires_exactly_once(self):
        """
        REGRESSION: three taps in quick succession must fire ONE double-tap
        (taps 1+2), not two (taps 1+2 then 2+3). Refractory clears history.
        """
        t = 0.0
        for i in range(20):
            self.d.update(make_imu(t)); t += 0.05
        fires = 0
        for tap_i in range(3):
            out = self.d.update(make_imu(t, az=2.2)); t += 0.05
            fires += out.double_tap
            for _ in range(2):
                out = self.d.update(make_imu(t)); t += 0.05
                fires += out.double_tap
        assert fires == 1, f"triple tap fired {fires} times, must be exactly 1"

    def test_sustained_spike_is_one_tap_not_many(self):
        """
        REGRESSION: a continuous 200ms spike (4 samples above threshold) is
        ONE tap event (edge-triggered), so alone it can never fire double-tap.
        """
        t = 0.0
        for i in range(20):
            self.d.update(make_imu(t)); t += 0.05
        fires = 0
        for _ in range(4):  # 200ms sustained spike
            out = self.d.update(make_imu(t, az=2.2)); t += 0.05
            fires += out.double_tap
        assert fires == 0, f"sustained spike fired {fires} times, must be 0"

    def test_change_point_detection(self):
        """Sudden jump in motion energy should flag a change-point."""
        t = 0.0
        # long quiet baseline
        for i in range(60):
            self.d.update(make_imu(t)); t += 0.05
        # sudden burst
        flagged = False
        import random
        rng = random.Random(2)
        for i in range(20):
            out = self.d.update(make_imu(t, ax=rng.gauss(0, 0.6),
                                         az=1.0 + rng.gauss(0, 0.6)))
            t += 0.05
            if out.change_point:
                flagged = True
        assert flagged


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
