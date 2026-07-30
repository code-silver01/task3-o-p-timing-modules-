"""
Chronis Task 3, Team B, Day 3 — Mock NTP Time Source.

Real hardware would ask an actual NTP server "what's the real time" and
compare it to the device's own clock to compute drift. This mock skips
the network entirely — a test just tells it "pretend the drift is X
milliseconds" and the daemon reacts to that number. Same reasoning as
every other mock clock in this sprint: deterministic, no real time
involved, no flaky tests.
"""


class MockNTPTimeSource:
    def __init__(self):
        self._drift_ms = 0

    def set_drift_ms(self, drift_ms: float):
        """Test setup calls this to say 'the device's clock is currently
        this far off from the real time server'. Can be negative (clock
        running fast) or positive (clock running slow) — the daemon only
        cares about the size of the drift, not the direction, for
        deciding which tier applies."""
        self._drift_ms = drift_ms

    def measure_drift_ms(self) -> float:
        return self._drift_ms