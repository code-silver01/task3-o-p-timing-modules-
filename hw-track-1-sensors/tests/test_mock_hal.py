"""
Test suite for Mock HAL — Day 1 deliverable.

Tests cover:
  - Every sensor returns valid readings when available
  - Rule 3: every sensor returns SensorUnavailable (never fake zero) when down
  - Rule 1: storage rejects raw unencrypted data
  - Rule 2: storage rejects overwrites and deletes
  - Sensor fault injection
  - PPG not-worn state
"""

import sys
import os
import pytest

# Add parent to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from mock_hal import (
    MockHAL, SensorStatus, UnavailableReason,
    IMUReading, PPGReading, AudioReading, CameraReading, GPIOReading,
    EncryptedPayload, RawPayload,
)
from mock_hal.mock_storage import MockStorage, AppendOnlyViolation, EncryptionBypassAttempt


# =========================================================
# IMU Tests
# =========================================================

class TestMockIMU:
    def setup_method(self):
        self.hal = MockHAL()

    def test_imu_returns_valid_reading(self):
        reading = self.hal.read_imu()
        assert reading.is_valid
        assert reading.status == SensorStatus.OK
        assert reading.accel_x is not None
        assert reading.accel_y is not None
        assert reading.accel_z is not None
        assert reading.gyro_x is not None
        assert reading.gyro_y is not None
        assert reading.gyro_z is not None

    def test_imu_default_upright(self):
        """Default: device upright, still. accel_z ~ 1g, others ~ 0."""
        reading = self.hal.read_imu()
        assert abs(reading.accel_z - 1.0) < 0.1  # ~1g on z
        assert abs(reading.accel_x) < 0.1
        assert abs(reading.accel_y) < 0.1

    def test_imu_unavailable_rule3(self):
        """Rule 3: unavailable sensor must NOT return fake zeros."""
        self.hal.imu.set_available(False, UnavailableReason.I2C_TIMEOUT)
        reading = self.hal.read_imu()

        assert not reading.is_valid
        assert reading.status == SensorStatus.UNAVAILABLE
        assert reading.unavailable_reason == UnavailableReason.I2C_TIMEOUT
        # Values must be None, NOT zero
        assert reading.accel_x is None
        assert reading.accel_y is None
        assert reading.accel_z is None
        assert reading.gyro_x is None

    def test_imu_fault(self):
        self.hal.imu.set_fault(True)
        reading = self.hal.read_imu()
        assert reading.status == SensorStatus.FAULT
        assert not reading.is_valid

    def test_imu_configurable_values(self):
        """Can set custom values to simulate different scenarios."""
        self.hal.imu.set_values(accel=(0.3, 0.1, 0.95), gyro=(5.0, -2.0, 1.0))
        self.hal.imu.set_noise(0.0)  # disable noise for exact check
        reading = self.hal.read_imu()
        assert reading.accel_x == 0.3
        assert reading.gyro_x == 5.0

    def test_imu_accel_magnitude(self):
        self.hal.imu.set_noise(0.0)
        self.hal.imu.set_values(accel=(0.0, 0.0, 1.0), gyro=(0, 0, 0))
        reading = self.hal.read_imu()
        assert abs(reading.accel_magnitude - 1.0) < 0.001

    def test_imu_magnitude_none_when_unavailable(self):
        self.hal.imu.set_available(False)
        reading = self.hal.read_imu()
        assert reading.accel_magnitude is None


# =========================================================
# PPG Tests
# =========================================================

class TestMockPPG:
    def setup_method(self):
        self.hal = MockHAL()

    def test_ppg_valid_reading(self):
        reading = self.hal.read_ppg()
        assert reading.is_valid
        assert reading.heart_rate_bpm is not None
        assert reading.spo2_percent is not None
        assert reading.signal_quality is not None

    def test_ppg_unavailable_rule3(self):
        self.hal.ppg.set_available(False, UnavailableReason.SENSOR_NOT_FOUND)
        reading = self.hal.read_ppg()
        assert not reading.is_valid
        assert reading.status == SensorStatus.UNAVAILABLE
        assert reading.heart_rate_bpm is None

    def test_ppg_not_worn_rule3(self):
        """Rule 3: not-worn must be explicit, never a fake zero heart rate."""
        self.hal.ppg.set_worn(False)
        reading = self.hal.read_ppg()
        assert not reading.is_valid
        assert reading.status == SensorStatus.NOT_WORN
        assert reading.unavailable_reason == UnavailableReason.DEVICE_NOT_WORN
        assert reading.heart_rate_bpm is None

    def test_ppg_signal_quality_range(self):
        reading = self.hal.read_ppg()
        assert 0.0 <= reading.signal_quality <= 1.0


# =========================================================
# Camera Tests
# =========================================================

class TestMockCamera:
    def setup_method(self):
        self.hal = MockHAL()

    def test_camera_valid_frame(self):
        reading = self.hal.capture_frame()
        assert reading.is_valid
        assert reading.frame_id is not None
        assert reading.width == 1920
        assert reading.height == 1080

    def test_camera_unavailable_rule3(self):
        self.hal.camera.set_available(False)
        reading = self.hal.capture_frame()
        assert not reading.is_valid
        assert reading.frame_id is None

    def test_camera_frame_counter_increments(self):
        f1 = self.hal.capture_frame()
        f2 = self.hal.capture_frame()
        assert f2.frame_id == f1.frame_id + 1

    def test_camera_face_detection(self):
        self.hal.camera.set_face(True, "smiling")
        reading = self.hal.capture_frame()
        assert reading.face_detected is True
        assert reading.face_expression == "smiling"


# =========================================================
# Audio Tests
# =========================================================

class TestMockMicrophone:
    def setup_method(self):
        self.hal = MockHAL()

    def test_audio_valid_reading(self):
        reading = self.hal.read_audio()
        assert reading.is_valid
        assert reading.energy_rms is not None
        assert reading.sample_rate_hz is not None

    def test_audio_unavailable_rule3(self):
        self.hal.microphone.set_available(False)
        reading = self.hal.read_audio()
        assert not reading.is_valid
        assert reading.energy_rms is None


# =========================================================
# GPIO Tests
# =========================================================

class TestMockGPIO:
    def setup_method(self):
        self.hal = MockHAL()

    def test_gpio_read(self):
        self.hal.gpio.set_pin(7, True)
        reading = self.hal.read_gpio(7)
        assert reading.is_valid
        assert reading.value is True

    def test_gpio_unknown_pin(self):
        reading = self.hal.read_gpio(99)
        assert not reading.is_valid
        assert reading.status == SensorStatus.UNAVAILABLE


# =========================================================
# Rule 1: Encryption-before-storage
# =========================================================

class TestRule1EncryptionEnforcement:
    def setup_method(self):
        self.storage = MockStorage()

    def test_encrypted_payload_accepted(self):
        payload = EncryptedPayload(
            ciphertext=b"encrypted_data_here",
            signature=b"sig_here",
            key_id="DSK-2026-07-12",
            timestamp=1000.0,
            source_daemon="camera",
        )
        assert self.storage.write("/vault/2026-07-12/camera/frame_001", payload)

    def test_raw_payload_rejected(self):
        """Rule 1: writing raw unencrypted data must FAIL."""
        raw = RawPayload(
            data=b"raw_sensor_data",
            source_daemon="camera",
            timestamp=1000.0,
        )
        with pytest.raises(EncryptionBypassAttempt):
            self.storage.write("/vault/2026-07-12/camera/frame_001", raw)

    def test_raw_bytes_rejected(self):
        """Rule 1: even plain bytes must fail."""
        with pytest.raises(EncryptionBypassAttempt):
            self.storage.write("/vault/test", b"raw bytes")

    def test_string_rejected(self):
        with pytest.raises(EncryptionBypassAttempt):
            self.storage.write("/vault/test", "just a string")

    def test_dict_rejected(self):
        with pytest.raises(EncryptionBypassAttempt):
            self.storage.write("/vault/test", {"data": "something"})


# =========================================================
# Rule 2: Append-only storage
# =========================================================

class TestRule2AppendOnly:
    def setup_method(self):
        self.storage = MockStorage()
        self.payload = EncryptedPayload(
            ciphertext=b"data", signature=b"sig",
            key_id="DSK-2026-07-12", timestamp=1000.0,
            source_daemon="imu",
        )

    def test_first_write_succeeds(self):
        assert self.storage.write("/vault/2026-07-12/sensors/imu/001", self.payload)

    def test_overwrite_fails(self):
        """Rule 2: overwriting an existing record must FAIL."""
        self.storage.write("/vault/2026-07-12/sensors/imu/001", self.payload)
        
        payload2 = EncryptedPayload(
            ciphertext=b"new_data", signature=b"sig2",
            key_id="DSK-2026-07-12", timestamp=1001.0,
            source_daemon="imu",
        )
        with pytest.raises(AppendOnlyViolation):
            self.storage.write("/vault/2026-07-12/sensors/imu/001", payload2)

    def test_delete_fails(self):
        """Rule 2: deletion must ALWAYS fail."""
        self.storage.write("/vault/2026-07-12/sensors/imu/001", self.payload)
        with pytest.raises(AppendOnlyViolation):
            self.storage.delete("/vault/2026-07-12/sensors/imu/001")

    def test_append_different_path_works(self):
        """Appending to a NEW path is fine — only same-path overwrites fail."""
        self.storage.write("/vault/2026-07-12/sensors/imu/001", self.payload)
        payload2 = EncryptedPayload(
            ciphertext=b"data2", signature=b"sig2",
            key_id="DSK-2026-07-12", timestamp=1001.0,
            source_daemon="imu",
        )
        assert self.storage.write("/vault/2026-07-12/sensors/imu/002", payload2)
        assert self.storage.write_count == 2


# =========================================================
# Full HAL toggle test
# =========================================================

class TestHALToggle:
    def test_all_sensors_unavailable(self):
        """Set all sensors unavailable at once and verify Rule 3 on each."""
        hal = MockHAL()
        hal.set_all_available(False)

        assert not hal.read_imu().is_valid
        assert not hal.read_ppg().is_valid
        assert not hal.capture_frame().is_valid
        assert not hal.read_audio().is_valid

    def test_all_sensors_restored(self):
        hal = MockHAL()
        hal.set_all_available(False)
        hal.set_all_available(True)

        assert hal.read_imu().is_valid
        assert hal.read_ppg().is_valid
        assert hal.capture_frame().is_valid
        assert hal.read_audio().is_valid


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
