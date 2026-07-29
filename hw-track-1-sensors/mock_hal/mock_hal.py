"""
Chronis HW-1 — Mock Hardware Abstraction Layer (HAL).

Simulates the real sensor chip APIs (ICM-42688-P IMU, MAX30102 PPG, IMX219 camera).
Every function here will eventually be swapped with a real i2c_read() / gpio_read()
call when hardware arrives — the logic above this layer stays identical.

Rule 3 enforced: every read function can return SensorUnavailable with a reason.
"""

import time
import random
from typing import Optional, List
from .sensor_types import (
    SensorStatus, UnavailableReason,
    IMUReading, PPGReading, AudioReading, CameraReading, GPIOReading,
)


class MockIMU:
    """
    Mock ICM-42688-P 6-axis IMU.
    Real chip uses I2C address 0x68, registers 0x3B-0x48.
    This mock returns configurable values or SensorUnavailable.
    """

    def __init__(self):
        self._available: bool = True
        self._fault: bool = False
        # Default values: device upright and still
        self._accel = (0.0, 0.0, 1.0)  # g (x, y, z) — 1g on z = upright
        self._gyro = (0.0, 0.0, 0.0)   # deg/s
        self._noise_level: float = 0.01  # gaussian noise added to readings

    def set_available(self, available: bool, reason: Optional[UnavailableReason] = None):
        """Simulate sensor becoming available/unavailable."""
        self._available = available
        self._unavail_reason = reason if not available else None

    def set_fault(self, fault: bool):
        """Simulate hardware fault."""
        self._fault = fault

    def set_values(self, accel: tuple, gyro: tuple):
        """Set the current fake sensor values."""
        self._accel = accel
        self._gyro = gyro

    def set_noise(self, level: float):
        """Set noise level for realistic simulation."""
        self._noise_level = level

    def _add_noise(self, value: float) -> float:
        return value + random.gauss(0, self._noise_level)

    def i2c_read(self) -> IMUReading:
        """
        Simulates i2c_read(0x68, 0x3B, 14) — reading 14 bytes from IMU.
        Returns IMUReading with status.
        """
        ts = time.time()

        if not self._available:
            return IMUReading(
                timestamp=ts,
                status=SensorStatus.UNAVAILABLE,
                unavailable_reason=getattr(self, '_unavail_reason',
                                           UnavailableReason.SENSOR_NOT_FOUND),
            )

        if self._fault:
            return IMUReading(
                timestamp=ts,
                status=SensorStatus.FAULT,
                unavailable_reason=UnavailableReason.HARDWARE_FAULT,
            )

        return IMUReading(
            timestamp=ts,
            status=SensorStatus.OK,
            accel_x=self._add_noise(self._accel[0]),
            accel_y=self._add_noise(self._accel[1]),
            accel_z=self._add_noise(self._accel[2]),
            gyro_x=self._add_noise(self._gyro[0]),
            gyro_y=self._add_noise(self._gyro[1]),
            gyro_z=self._add_noise(self._gyro[2]),
        )


class MockPPG:
    """
    Mock MAX30102 heart-rate / SpO2 sensor.
    Real chip uses I2C address 0x57.
    """

    def __init__(self):
        self._available: bool = True
        self._worn: bool = True
        self._heart_rate: float = 72.0
        self._spo2: float = 98.0
        self._signal_quality: float = 0.85
        self._noise_level: float = 1.0

    def set_available(self, available: bool, reason: Optional[UnavailableReason] = None):
        self._available = available
        self._unavail_reason = reason if not available else None

    def set_worn(self, worn: bool):
        """Simulate skin contact. No contact = no valid reading."""
        self._worn = worn

    def set_values(self, heart_rate: float, spo2: float = 98.0,
                   signal_quality: float = 0.85):
        self._heart_rate = heart_rate
        self._spo2 = spo2
        self._signal_quality = signal_quality

    def i2c_read(self) -> PPGReading:
        """Simulates i2c_read(0x57, ...) — reading PPG sensor."""
        ts = time.time()

        if not self._available:
            return PPGReading(
                timestamp=ts,
                status=SensorStatus.UNAVAILABLE,
                unavailable_reason=getattr(self, '_unavail_reason',
                                           UnavailableReason.SENSOR_NOT_FOUND),
            )

        if not self._worn:
            return PPGReading(
                timestamp=ts,
                status=SensorStatus.NOT_WORN,
                unavailable_reason=UnavailableReason.DEVICE_NOT_WORN,
            )

        # Simulate realistic IR/red photodiode values
        ir = int(50000 + random.gauss(0, 500))
        red = int(45000 + random.gauss(0, 500))

        return PPGReading(
            timestamp=ts,
            status=SensorStatus.OK,
            heart_rate_bpm=self._heart_rate + random.gauss(0, self._noise_level),
            spo2_percent=min(100.0, self._spo2 + random.gauss(0, 0.3)),
            ir_value=ir,
            red_value=red,
            signal_quality=max(0.0, min(1.0,
                self._signal_quality + random.gauss(0, 0.05))),
        )


class MockCamera:
    """
    Mock IMX219 camera sensor.
    Returns frame metadata (no actual pixels in simulation).
    """

    def __init__(self):
        self._available: bool = True
        self._frame_counter: int = 0
        self._resolution = (1920, 1080)
        self._face_detected: bool = False
        self._face_expression: str = "neutral"

    def set_available(self, available: bool, reason: Optional[UnavailableReason] = None):
        self._available = available
        self._unavail_reason = reason if not available else None

    def set_face(self, detected: bool, expression: str = "neutral"):
        self._face_detected = detected
        self._face_expression = expression

    def capture_frame(self, compression: str = "moderate") -> CameraReading:
        """Simulate camera frame capture."""
        ts = time.time()

        if not self._available:
            return CameraReading(
                timestamp=ts,
                status=SensorStatus.UNAVAILABLE,
                unavailable_reason=getattr(self, '_unavail_reason',
                                           UnavailableReason.SENSOR_NOT_FOUND),
            )

        self._frame_counter += 1
        return CameraReading(
            timestamp=ts,
            status=SensorStatus.OK,
            frame_id=self._frame_counter,
            width=self._resolution[0],
            height=self._resolution[1],
            compression_level=compression,
            face_detected=self._face_detected,
            face_expression=self._face_expression if self._face_detected else None,
        )


class MockMicrophone:
    """
    Mock audio input (MEMS microphone array).
    Returns audio chunk metadata.
    """

    def __init__(self):
        self._available: bool = True
        self._energy: float = 0.1
        self._speech_detected: bool = False
        self._num_speakers: int = 0
        self._sample_rate: int = 16000

    def set_available(self, available: bool, reason: Optional[UnavailableReason] = None):
        self._available = available
        self._unavail_reason = reason if not available else None

    def set_values(self, energy: float, speech_detected: bool = False,
                   num_speakers: int = 0):
        self._energy = energy
        self._speech_detected = speech_detected
        self._num_speakers = num_speakers

    def set_sample_rate(self, rate: int):
        self._sample_rate = rate

    def read_chunk(self) -> AudioReading:
        """Simulate reading an audio chunk."""
        ts = time.time()

        if not self._available:
            return AudioReading(
                timestamp=ts,
                status=SensorStatus.UNAVAILABLE,
                unavailable_reason=getattr(self, '_unavail_reason',
                                           UnavailableReason.SENSOR_NOT_FOUND),
            )

        energy = max(0.0, min(1.0, self._energy + random.gauss(0, 0.02)))
        peak_db = -60 + (energy * 80)  # map 0-1 to -60dB to +20dB

        return AudioReading(
            timestamp=ts,
            status=SensorStatus.OK,
            energy_rms=energy,
            peak_db=peak_db,
            sample_rate_hz=self._sample_rate,
            speech_detected=self._speech_detected,
            num_speakers=self._num_speakers,
        )


class MockGPIO:
    """Mock GPIO pins — simple digital reads."""

    def __init__(self):
        self._pins: dict = {}  # pin_id -> bool
        self._available: bool = True

    def set_pin(self, pin_id: int, value: bool):
        self._pins[pin_id] = value

    def set_available(self, available: bool):
        self._available = available

    def gpio_read(self, pin_id: int) -> GPIOReading:
        ts = time.time()

        if not self._available:
            return GPIOReading(
                timestamp=ts,
                status=SensorStatus.UNAVAILABLE,
                unavailable_reason=UnavailableReason.SENSOR_NOT_FOUND,
            )

        if pin_id not in self._pins:
            return GPIOReading(
                timestamp=ts,
                status=SensorStatus.UNAVAILABLE,
                unavailable_reason=UnavailableReason.SENSOR_NOT_FOUND,
                pin_id=pin_id,
            )

        return GPIOReading(
            timestamp=ts,
            status=SensorStatus.OK,
            pin_id=pin_id,
            value=self._pins[pin_id],
        )


class MockHAL:
    """
    Complete Mock Hardware Abstraction Layer.

    Groups all sensor mocks into one interface.
    When real hardware arrives, replace this class with RealHAL
    that calls actual I2C/SPI/GPIO drivers — all daemon code above
    this layer stays untouched.
    """

    def __init__(self):
        self.imu = MockIMU()
        self.ppg = MockPPG()
        self.camera = MockCamera()
        self.microphone = MockMicrophone()
        self.gpio = MockGPIO()

    def read_imu(self) -> IMUReading:
        return self.imu.i2c_read()

    def read_ppg(self) -> PPGReading:
        return self.ppg.i2c_read()

    def capture_frame(self, compression: str = "moderate") -> CameraReading:
        return self.camera.capture_frame(compression)

    def read_audio(self) -> AudioReading:
        return self.microphone.read_chunk()

    def read_gpio(self, pin_id: int) -> GPIOReading:
        return self.gpio.gpio_read(pin_id)

    def set_all_available(self, available: bool):
        """Quick toggle for all sensors."""
        reason = UnavailableReason.SENSOR_NOT_FOUND if not available else None
        self.imu.set_available(available, reason)
        self.ppg.set_available(available, reason)
        self.camera.set_available(available, reason)
        self.microphone.set_available(available, reason)
        self.gpio.set_available(available)
