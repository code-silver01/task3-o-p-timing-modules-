"""
Chronis HW-1 — Heart Rate Sensor Daemon.

Consumes PPG readings and produces a trustworthy heart-rate estimate plus a
running signal-quality score. Low-quality readings are FLAGGED, never presented
as confident values (Rule 3 spirit: don't fake certainty you don't have).
"""

import math
from dataclasses import dataclass
from enum import Enum
from collections import deque
from typing import Optional, Deque

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from mock_hal.sensor_types import PPGReading, SensorStatus


class HRQuality(Enum):
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"
    UNAVAILABLE = "unavailable"


@dataclass
class HeartRateOutput:
    timestamp: float
    valid: bool
    heart_rate_bpm: Optional[float] = None
    signal_quality: Optional[float] = None      # 0..1
    quality_label: HRQuality = HRQuality.UNAVAILABLE
    trustworthy: bool = False                    # True only if quality high enough
    unavailable_reason: Optional[str] = None


class HeartRateDaemon:
    """
    Scores how trustworthy the current heart-rate reading is by combining:
      - the sensor's own reported signal_quality
      - beat-to-beat stability (sudden jumps = suspicious)
      - how physiologically plausible the value is (30-220 bpm)
    """

    def __init__(self, window: int = 10):
        self._hr_history: Deque[float] = deque(maxlen=window)
        self.GOOD_THRESHOLD = 0.7
        self.FAIR_THRESHOLD = 0.4
        self.TRUST_THRESHOLD = 0.6   # below this, don't trust the reading
        self.PLAUSIBLE_MIN = 30.0
        self.PLAUSIBLE_MAX = 220.0

    def _stability_score(self, hr: float) -> float:
        """1.0 if HR is consistent with recent history, lower if it jumps."""
        if len(self._hr_history) < 3:
            return 0.8  # not enough history; neutral-ish
        mean = sum(self._hr_history) / len(self._hr_history)
        # a jump of >25 bpm from recent mean is suspicious
        jump = abs(hr - mean)
        return max(0.0, 1.0 - (jump / 40.0))

    def _plausibility(self, hr: float) -> float:
        if self.PLAUSIBLE_MIN <= hr <= self.PLAUSIBLE_MAX:
            return 1.0
        return 0.0

    def update(self, reading: PPGReading) -> HeartRateOutput:
        # Rule 3: not-worn or unavailable -> explicit, never fake HR
        if not reading.is_valid:
            reason = (reading.unavailable_reason.value
                      if reading.unavailable_reason else "unknown")
            return HeartRateOutput(
                timestamp=reading.timestamp,
                valid=False,
                quality_label=HRQuality.UNAVAILABLE,
                trustworthy=False,
                unavailable_reason=reason,
            )

        hr = reading.heart_rate_bpm
        sensor_q = reading.signal_quality if reading.signal_quality is not None else 0.5

        stability = self._stability_score(hr)
        plausible = self._plausibility(hr)

        # combined quality: plausibility gates hard (0 if impossible HR).
        # Sensor-reported quality dominates (0.7) — if the sensor says the
        # signal is poor, we don't override that with stability/plausibility.
        combined = plausible * (0.7 * sensor_q + 0.3 * stability)

        # only add to history if plausible (don't let garbage poison stability)
        if plausible > 0:
            self._hr_history.append(hr)

        if combined >= self.GOOD_THRESHOLD:
            label = HRQuality.GOOD
        elif combined >= self.FAIR_THRESHOLD:
            label = HRQuality.FAIR
        else:
            label = HRQuality.POOR

        trustworthy = combined >= self.TRUST_THRESHOLD

        return HeartRateOutput(
            timestamp=reading.timestamp,
            valid=True,
            heart_rate_bpm=round(hr, 1),
            signal_quality=round(combined, 3),
            quality_label=label,
            trustworthy=trustworthy,
        )
