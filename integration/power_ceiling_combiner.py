"""
Chronis — Day 5 Integration: capture level x power ceiling combination.

Sprint doc, Day 5: "if the state machine says L5 is warranted but the battery
is in Critical state (which caps at L3), the lower of the two must always win."

This is HW-1's side of that contract, prepared ahead of integration day so
wiring with HW-2's power daemon is a one-line hookup. HW-2's power daemon
provides the ceiling; we provide this combiner and the effective-level logic.

Interface expected from HW-2 (Rule 4: a clean seam, not internal access):
    power_daemon.current_ceiling() -> Level   (e.g. Level.L3 when Critical)
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'hw-track-1-sensors'))
from state_machine.capture_state_machine import Level, LEVEL_CONFIG


def effective_level(state_machine_level: Level, power_ceiling: Level) -> Level:
    """The lower of the two always wins. Test this exact conflict case."""
    return min(state_machine_level, power_ceiling)


def effective_config(state_machine_level: Level, power_ceiling: Level) -> dict:
    """Capture config after applying the power ceiling."""
    return LEVEL_CONFIG[effective_level(state_machine_level, power_ceiling)]


# ---- self-test (runs standalone; formal wiring happens on Day 5) ----
if __name__ == "__main__":
    # The exact conflict case from the sprint doc:
    sm_says = Level.L5          # state machine: peak moment!
    battery_critical_cap = Level.L3   # power daemon: battery Critical

    result = effective_level(sm_says, battery_critical_cap)
    assert result == Level.L3, "lower of the two must always win"
    print(f"SM wants {sm_says.name}, power caps at {battery_critical_cap.name} "
          f"-> effective {result.name}  [OK]")

    # No ceiling: full-battery case
    assert effective_level(Level.L4, Level.L5) == Level.L4
    print("No-restriction case: SM L4 with power ceiling L5 -> L4  [OK]")
