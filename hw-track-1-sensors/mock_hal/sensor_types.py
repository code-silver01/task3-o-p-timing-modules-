"""
Chronis HW-1 — Core sensor data types.

Every sensor reading in the system uses these types.
Rule 3 enforced here: SensorUnavailable is NEVER a zero — it's a distinct state.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional
import time


class SensorStatus(Enum):
    """Status of a sensor reading."""
    OK = auto()
    UNAVAILABLE = auto()       # sensor physically not responding
    NOT_WORN = auto()          # device not on body — PPG meaningless
    CALIBRATING = auto()       # sensor still warming up
    FAULT = auto()             # sensor returned garbage / hardware error


class UnavailableReason(Enum):
    """Why a sensor is unavailable — Rule 3: always explain, never silently zero."""
    SENSOR_NOT_FOUND = "sensor not found on bus"
    I2C_TIMEOUT = "I2C read timed out"
    DEVICE_NOT_WORN = "device not worn — skin contact lost"
    SELF_TEST_FAILED = "sensor self-test failed"
    POWER_SAVING = "sensor disabled for power saving"
    HARDWARE_FAULT = "hardware fault detected"


@dataclass
class SensorReading:
    """
    Base class for all sensor readings.

    If status != OK, the `value` fields should be None.
    Downstream code MUST check status before using values.
    """
    timestamp: float
    status: SensorStatus
    unavailable_reason: Optional[UnavailableReason] = None

    @property
    def is_valid(self) -> bool:
        return self.status == SensorStatus.OK


@dataclass
class IMUReading(SensorReading):
    """6-axis IMU reading: accelerometer (g) + gyroscope (deg/s)."""
    accel_x: Optional[float] = None
    accel_y: Optional[float] = None
    accel_z: Optional[float] = None
    gyro_x: Optional[float] = None
    gyro_y: Optional[float] = None
    gyro_z: Optional[float] = None

    @property
    def accel_magnitude(self) -> Optional[float]:
        if not self.is_valid:
            return None
        return (self.accel_x**2 + self.accel_y**2 + self.accel_z**2) ** 0.5


@dataclass
class PPGReading(SensorReading):
    """Heart-rate / PPG sensor reading."""
    heart_rate_bpm: Optional[float] = None
    spo2_percent: Optional[float] = None
    ir_value: Optional[int] = None        # raw IR photodiode
    red_value: Optional[int] = None       # raw red LED photodiode
    signal_quality: Optional[float] = None  # 0.0 to 1.0


@dataclass
class AudioReading(SensorReading):
    """Audio chunk metadata (not raw audio — just energy/level info)."""
    energy_rms: Optional[float] = None    # RMS energy level (0.0 to 1.0)
    peak_db: Optional[float] = None       # peak dB level
    sample_rate_hz: Optional[int] = None  # current sample rate
    speech_detected: Optional[bool] = None
    num_speakers: Optional[int] = None


@dataclass
class CameraReading(SensorReading):
    """Camera frame metadata (mock — no actual pixel data)."""
    frame_id: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    compression_level: Optional[str] = None  # 'heavy', 'moderate', 'low', 'minimal', 'none'
    face_detected: Optional[bool] = None
    face_expression: Optional[str] = None    # 'neutral', 'smiling', 'surprised', etc.


@dataclass
class GPIOReading(SensorReading):
    """Simple GPIO pin read — high/low."""
    pin_id: Optional[int] = None
    value: Optional[bool] = None  # True = HIGH, False = LOW


# ---- Encryption enforcement types (Rule 1) ----

@dataclass
class EncryptedPayload:
    """
    Wrapper that marks data as encrypted.

    Rule 1: storage-write functions ONLY accept this type.
    Raw bytes can never be written to disk.
    """
    ciphertext: bytes
    signature: bytes
    key_id: str
    timestamp: float
    source_daemon: str


@dataclass
class RawPayload:
    """
    Raw unencrypted data.
    
    This type exists so that storage-write functions can REFUSE it.
    If you try to pass this to a write function, it should raise TypeError.
    """
    data: bytes
    source_daemon: str
    timestamp: float
