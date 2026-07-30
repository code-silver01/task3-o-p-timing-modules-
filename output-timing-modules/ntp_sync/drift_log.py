"""
Chronis Task 3, Team B, Day 3 — Persistent Drift Log.

The spec asks for "the persistent drift log file" — persistent meaning it
survives a daemon restart, so it can't just be a Python list in memory.
This writes one JSON object per line to an actual file on disk, same
format decision as Task 2's TelemetryLogger.as_jsonl() — reusing a
convention already established in this codebase rather than inventing a
second logging format.
"""

import json
import time
from dataclasses import dataclass, asdict


@dataclass
class DriftLogEntry:
    timestamp: float
    drift_ms: float
    tier: str                  # "slew" / "step_logged" / "step_alert"
    phone_alert_sent: bool

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)


class DriftLog:
    def __init__(self, path: str):
        self.path = path

    def append(self, drift_ms: float, tier: str, phone_alert_sent: bool = False):
        entry = DriftLogEntry(
            timestamp=time.time(),
            drift_ms=drift_ms,
            tier=tier,
            phone_alert_sent=phone_alert_sent,
        )
        # 'a' = append, never overwrite — same append-only spirit as the
        # permanent record in Task 2, for the same reason: a log you can
        # silently rewrite isn't trustworthy as a log.
        with open(self.path, "a") as f:
            f.write(entry.to_json() + "\n")
        return entry

    def read_all(self):
        """Reads every entry back from disk — proves the log actually
        persisted, not just that append() ran without error."""
        entries = []
        try:
            with open(self.path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        entries.append(json.loads(line))
        except FileNotFoundError:
            pass
        return entries