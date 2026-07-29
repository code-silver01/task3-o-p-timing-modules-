"""
Chronis HW-1 — Motion Sensor Daemon.

Consumes IMU readings and produces higher-level motion understanding:
  - Orientation (pitch/roll) via complementary filter
  - Motion state: still / walking / active
  - Posture: upright / lying
  - Gesture energy score
  - Change-point detection (sudden shift in motion pattern)
  - Double-tap detection (two taps within 300ms)

All logic runs on IMUReading objects — Rule 3 respected: if a reading is
invalid, the daemon flags the output as unavailable rather than trusting zeros.
"""

import math
from dataclasses import dataclass, field
from enum import Enum, auto
from collections import deque
from typing import Optional, Deque, List

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from mock_hal.sensor_types import IMUReading, SensorStatus


class MotionState(Enum):
    STILL = "still"
    WALKING = "walking"
    ACTIVE = "active"
    UNAVAILABLE = "unavailable"   # Rule 3: explicit, not a fake "still"


class Posture(Enum):
    UPRIGHT = "upright"
    LYING = "lying"
    UNKNOWN = "unknown"


@dataclass
class MotionOutput:
    """Everything the motion daemon knows at one instant."""
    timestamp: float
    valid: bool
    pitch_deg: Optional[float] = None
    roll_deg: Optional[float] = None
    motion_state: MotionState = MotionState.UNAVAILABLE
    posture: Posture = Posture.UNKNOWN
    gesture_energy: Optional[float] = None
    change_point: bool = False
    double_tap: bool = False
    unavailable_reason: Optional[str] = None


class ComplementaryFilter:
    """
    Fuses accelerometer (absolute but noisy) and gyroscope (smooth but drifts)
    into a stable pitch/roll estimate.

    pitch/roll from accel = trustworthy long-term
    gyro integration = trustworthy short-term
    alpha weights how much we trust gyro vs accel each step.
    """

    def __init__(self, alpha: float = 0.98):
        self.alpha = alpha
        self.pitch = 0.0
        self.roll = 0.0
        self._initialized = False

    def update(self, reading: IMUReading, dt: float):
        if not reading.is_valid:
            return  # keep last estimate; caller flags invalidity

        ax, ay, az = reading.accel_x, reading.accel_y, reading.accel_z
        gx, gy = reading.gyro_x, reading.gyro_y

        # Accelerometer-derived angles (degrees)
        accel_pitch = math.degrees(math.atan2(ax, math.sqrt(ay*ay + az*az)))
        accel_roll = math.degrees(math.atan2(ay, math.sqrt(ax*ax + az*az)))

        if not self._initialized:
            self.pitch = accel_pitch
            self.roll = accel_roll
            self._initialized = True
            return

        # Integrate gyro (deg/s * s = deg) then blend
        gyro_pitch = self.pitch + gy * dt
        gyro_roll = self.roll + gx * dt

        self.pitch = self.alpha * gyro_pitch + (1 - self.alpha) * accel_pitch
        self.roll = self.alpha * gyro_roll + (1 - self.alpha) * accel_roll


class MotionDaemon:
    """
    The motion sensor daemon. Feed it IMU readings one at a time via update().
    """

    def __init__(self, sample_rate_hz: float = 20.0):
        self.dt = 1.0 / sample_rate_hz
        self.filter = ComplementaryFilter()

        # rolling windows for motion classification & change detection
        self._accel_window: Deque[float] = deque(maxlen=int(sample_rate_hz))  # 1s
        self._energy_history: Deque[float] = deque(maxlen=int(sample_rate_hz * 2))  # 2s

        # double-tap detection state
        self._tap_timestamps: Deque[float] = deque(maxlen=4)
        self._last_tap_processed: float = -1.0
        self._in_spike: bool = False   # edge detection: are we already inside a spike?

        # tunable thresholds (would be calibrated on real hardware)
        self.STILL_VAR_THRESHOLD = 0.004    # accel variance below this = still
        self.WALKING_VAR_THRESHOLD = 0.05   # between still and this = walking
        self.TAP_SPIKE_THRESHOLD = 0.6      # accel deviation above 1g to count as a tap
        self.TAP_WINDOW_S = 0.300           # two taps within 300ms
        self.CHANGE_POINT_RATIO = 3.0       # recent energy vs baseline ratio to flag

    def _detect_tap(self, reading: IMUReading) -> bool:
        """
        A tap = the RISING EDGE of a sharp accel deviation from ~1g.

        Edge-triggered, not level-triggered: a sustained 200ms spike is ONE
        tap event (registered when it starts), not one per sample. Without
        this, a long spike registers as many "taps" and false-fires the
        double-tap detector.
        """
        mag = reading.accel_magnitude
        if mag is None:
            self._in_spike = False
            return False
        above = abs(mag - 1.0) > self.TAP_SPIKE_THRESHOLD
        is_edge = above and not self._in_spike   # only the transition counts
        self._in_spike = above
        return is_edge

    def _check_double_tap(self, t: float, is_tap: bool) -> bool:
        """
        Register taps; return True exactly once when two taps land within the
        300ms window. After firing, the tap history is cleared (refractory) so
        a third tap cannot pair with the second and fire again.
        """
        if is_tap:
            self._tap_timestamps.append(t)

        if len(self._tap_timestamps) >= 2:
            t1, t2 = self._tap_timestamps[-2], self._tap_timestamps[-1]
            if 0 < (t2 - t1) <= self.TAP_WINDOW_S and t2 > self._last_tap_processed:
                self._last_tap_processed = t2
                self._tap_timestamps.clear()   # refractory: triple-tap fires once
                return True
        return False

    def _classify_motion(self) -> MotionState:
        """Classify based on variance of accel magnitude over the window."""
        if len(self._accel_window) < 3:
            return MotionState.STILL
        mean = sum(self._accel_window) / len(self._accel_window)
        var = sum((x - mean) ** 2 for x in self._accel_window) / len(self._accel_window)
        if var < self.STILL_VAR_THRESHOLD:
            return MotionState.STILL
        elif var < self.WALKING_VAR_THRESHOLD:
            return MotionState.WALKING
        else:
            return MotionState.ACTIVE

    def _classify_posture(self) -> Posture:
        """Upright if pitch/roll near 0 (z-axis vertical); lying otherwise."""
        if not self.filter._initialized:
            return Posture.UNKNOWN
        # If device is upright, gravity is on z, so pitch & roll near 0.
        tilt = math.sqrt(self.filter.pitch**2 + self.filter.roll**2)
        return Posture.UPRIGHT if tilt < 45.0 else Posture.LYING

    def _gesture_energy(self) -> float:
        """Windowed RMS of accel deviation from 1g."""
        if not self._accel_window:
            return 0.0
        sq = [(x - 1.0) ** 2 for x in self._accel_window]
        return math.sqrt(sum(sq) / len(sq))

    def _detect_change_point(self, current_energy: float) -> bool:
        """
        Flag if recent energy jumps sharply vs the longer baseline.
        Simple, robust: compare last-0.5s mean to prior baseline mean.
        """
        if len(self._energy_history) < self._energy_history.maxlen:
            return False
        hist = list(self._energy_history)
        half = len(hist) // 2
        baseline = sum(hist[:half]) / half
        recent = sum(hist[half:]) / (len(hist) - half)
        if baseline < 1e-6:
            return recent > 0.05
        return (recent / baseline) > self.CHANGE_POINT_RATIO

    def update(self, reading: IMUReading) -> MotionOutput:
        """Process one IMU reading, return the full motion picture."""
        # Rule 3: invalid reading -> explicit unavailable output
        if not reading.is_valid:
            reason = (reading.unavailable_reason.value
                      if reading.unavailable_reason else "unknown")
            return MotionOutput(
                timestamp=reading.timestamp,
                valid=False,
                motion_state=MotionState.UNAVAILABLE,
                posture=Posture.UNKNOWN,
                unavailable_reason=reason,
            )

        # orientation
        self.filter.update(reading, self.dt)

        # update windows
        mag = reading.accel_magnitude
        self._accel_window.append(mag)
        energy = self._gesture_energy()
        self._energy_history.append(energy)

        # detections
        is_tap = self._detect_tap(reading)
        double_tap = self._check_double_tap(reading.timestamp, is_tap)
        motion_state = self._classify_motion()
        posture = self._classify_posture()
        change_point = self._detect_change_point(energy)

        return MotionOutput(
            timestamp=reading.timestamp,
            valid=True,
            pitch_deg=round(self.filter.pitch, 2),
            roll_deg=round(self.filter.roll, 2),
            motion_state=motion_state,
            posture=posture,
            gesture_energy=round(energy, 4),
            change_point=change_point,
            double_tap=double_tap,
        )
