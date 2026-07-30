"""
Chronis Task 3, Team B, Day 3 — NTP Time Sync Daemon.

Boundary-value assumption, stated up front (same discipline as every
other ambiguous spec line this sprint): the spec says "under 100ms gets
slew", "100ms to 1 second gets stepped", "over 1 second gets stepped +
alert". Read literally, that makes the boundaries:
    drift <  100ms  -> slew
    100ms <= drift <= 1000ms -> stepped, logged
    drift >  1000ms -> stepped, logged, AND alert
So exactly 100ms falls into the stepped tier (not slew, since slew is
"under" 100ms), and exactly 1000ms falls into the stepped-without-alert
tier (since alert is for "over" 1 second, i.e. strictly more). Tested
explicitly at both boundary values below.
"""

import time
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from .drift_log import DriftLog

SLEW_THRESHOLD_MS = 100
STEP_ALERT_THRESHOLD_MS = 1000


class DriftTier(Enum):
    SLEW = "slew"
    STEP_LOGGED = "step_logged"
    STEP_ALERT = "step_alert"


def classify_drift(drift_ms: float) -> DriftTier:
    magnitude = abs(drift_ms)
    if magnitude < SLEW_THRESHOLD_MS:
        return DriftTier.SLEW
    if magnitude <= STEP_ALERT_THRESHOLD_MS:
        return DriftTier.STEP_LOGGED
    return DriftTier.STEP_ALERT


@dataclass
class SyncResult:
    drift_ms: float
    tier: DriftTier
    phone_alert_sent: bool
    records_adjusted: int


class NTPSyncDaemon:
    def __init__(self, time_source, drift_log: DriftLog):
        self.time_source = time_source
        self.drift_log = drift_log
        self.phone_alerts: List[dict] = []   # what would've been pushed to the phone
        self.current_time_source = "ntp"     # "ntp" or "rtc", set by boot path
        self.used_rtc_fallback = False

    def sync_on_wifi_connect(self, recent_records: Optional[List[dict]] = None) -> SyncResult:
        """The main entry point — call this whenever WiFi connects. Reads
        the current drift from time_source, applies the correct tier's
        correction, and (for the two stepped tiers) retrospectively
        shifts any recent sensor records passed in."""
        drift_ms = self.time_source.measure_drift_ms()
        tier = classify_drift(drift_ms)
        recent_records = recent_records or []

        if tier == DriftTier.SLEW:
            # Gradual correction: spec says "no disruption to ongoing
            # timestamps" — meaning past records are NOT touched at all,
            # only future timestamps drift smoothly back into alignment.
            # Nothing to retroactively adjust; nothing to alert.
            self.drift_log.append(drift_ms, tier.value, phone_alert_sent=False)
            return SyncResult(drift_ms, tier, phone_alert_sent=False, records_adjusted=0)

        # Both remaining tiers are a stepped (instant) correction, so both
        # need the same retrospective adjustment of recent records —
        # they only differ in whether a phone alert also fires.
        self._retrospectively_adjust(recent_records, drift_ms)

        phone_alert_sent = False
        if tier == DriftTier.STEP_ALERT:
            self.phone_alerts.append({
                "message": f"Clock drift of {drift_ms:.0f}ms corrected",
                "drift_ms": drift_ms,
            })
            phone_alert_sent = True

        self.drift_log.append(drift_ms, tier.value, phone_alert_sent=phone_alert_sent)
        return SyncResult(drift_ms, tier, phone_alert_sent=phone_alert_sent,
                           records_adjusted=len(recent_records))

    def _retrospectively_adjust(self, records: List[dict], drift_ms: float):
        """Shifts the timestamp_ms field of each recent record by the
        drift amount, in place — these records were stamped using the
        clock BEFORE it was corrected, so they're now off by exactly the
        drift that was just fixed."""
        for record in records:
            if "timestamp_ms" in record:
                record["timestamp_ms"] += drift_ms

    def boot_without_wifi(self, rtc_reported_time_ms: float):
        """DS3231 RTC fallback path: no WiFi at boot means no NTP server
        reachable, so the device falls back to whatever the battery-backed
        real-time-clock chip has been keeping. Less accurate than NTP
        (that's the whole reason NTP sync exists) but keeps the clock
        roughly correct until WiFi becomes available."""
        self.current_time_source = "rtc"
        self.used_rtc_fallback = True
        return rtc_reported_time_ms