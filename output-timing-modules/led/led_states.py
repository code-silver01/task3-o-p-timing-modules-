"""
Chronis Task 3, Team B, Day 1 — LED States.

Fact-check note, stated honestly rather than papered over: the task doc
says "implement all twelve automatic states" but the comma-separated list
right after that sentence names 9 distinct animations plus one
CSE-dependent indicator = 10 distinct visual behaviors. There is no 11th
or 12th name given anywhere in the doc. Rather than invent two states that
were never specified (which would mean guessing at behavior nobody asked
for), this implements exactly the 10 that ARE named, plus the implicit
"nothing is happening" baseline (IDLE_OFF) as the 11th enum value — and
flags the count gap here so it's visible, not silently rounded up to 12.
"""

from enum import Enum


class LEDState(Enum):
    CHARGING_FILL = "charging_fill_animation"
    SYNC_CHASE = "sync_chase"
    LOW_BATTERY_PULSE = "low_battery_pulse"
    NEW_INSIGHT_FLASH = "new_insight_flash"
    NOT_WORN_BREATHING_AMBER = "not_worn_breathing_amber"     # back zones
    KILL_SWITCH_CONFIRMATION_FLASH = "kill_switch_confirmation_flash"
    TAMPER_ALERT_PULSE = "tamper_alert_pulse"
    BLE_PAIRING_CHASE = "ble_pairing_chase"
    MODE_CHANGE_CONFIRMATION_FLASH = "mode_change_confirmation_flash"
    CAPTURE_ACTIVE_DIM = "capture_active_dim"                  # CSE L4-L5 only
    IDLE_OFF = "idle_off"                                      # baseline / no event


# The task doc is explicit: "the user can disable every automatic state
# except two." These two must never go dark, no matter what the user's
# preferences say — that's a safety property, not a display preference.
UNSUPPRESSIBLE = {
    LEDState.TAMPER_ALERT_PULSE,
    LEDState.KILL_SWITCH_CONFIRMATION_FLASH,
}
