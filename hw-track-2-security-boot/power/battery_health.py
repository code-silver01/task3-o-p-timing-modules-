"""
Battery health tracker (Day 3).
Coulomb counting against mock charge/discharge data.
Flags replacement at 500 simulated charge cycles — not before.
"""

from dataclasses import dataclass


REPLACEMENT_CYCLE_THRESHOLD = 500


@dataclass
class BatteryHealthReport:
    charge_cycles: float
    replacement_needed: bool
    message: str


class BatteryHealthTracker:
    """
    Tracks partial and full charge cycles via Coulomb counting on mock data.
    One "cycle" = 100% of battery capacity discharged (may span multiple partial charges).
    """

    def __init__(self):
        self._accumulated_discharge_pct: float = 0.0
        self._full_cycles: float = 0.0

    def record_discharge(self, percent_discharged: float) -> None:
        """Record a discharge event. percent_discharged is 0–100."""
        if percent_discharged < 0:
            raise ValueError("percent_discharged cannot be negative")
        self._accumulated_discharge_pct += percent_discharged
        # Convert accumulated discharge to full cycles
        self._full_cycles = self._accumulated_discharge_pct / 100.0

    def report(self) -> BatteryHealthReport:
        replacement = self._full_cycles >= REPLACEMENT_CYCLE_THRESHOLD
        return BatteryHealthReport(
            charge_cycles=self._full_cycles,
            replacement_needed=replacement,
            message=(
                "Battery replacement may be needed soon."
                if replacement
                else f"Battery healthy ({self._full_cycles:.1f} cycles)."
            ),
        )

    @property
    def cycle_count(self) -> float:
        return self._full_cycles
