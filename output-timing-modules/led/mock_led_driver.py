"""
Chronis Task 3, Team B, Day 1 — Mock LED Driver.

This is the pretend hardware. A real Radxa Zero 3W would talk to actual
LEDs over GPIO/PWM pins; we don't have that board yet, so this class is
just two in-memory lists that stand in for "the current brightness of
every LED right now." Nothing here is smart — it just remembers numbers.
All the actual decision-making lives in led_controller.py.
"""

NUM_FRONT = 12   # front-arc LEDs, arranged in a ring
NUM_BACK = 3     # separately addressable back zones


class MockLEDDriver:
    def __init__(self):
        # brightness per LED, 0 (off) to 255 (max) — a plain list standing
        # in for "12 wires we could turn on/off/dim" on real hardware
        self.front = [0] * NUM_FRONT
        self.back = [0] * NUM_BACK

    def set_front(self, pattern):
        if len(pattern) != NUM_FRONT:
            raise ValueError(f"front pattern must have {NUM_FRONT} values, got {len(pattern)}")
        self.front = list(pattern)

    def set_back(self, pattern):
        if len(pattern) != NUM_BACK:
            raise ValueError(f"back pattern must have {NUM_BACK} values, got {len(pattern)}")
        self.back = list(pattern)

    def snapshot(self):
        """What a test (or a real status command) reads back to see 'what
        do the LEDs look like right now'."""
        return {"front": list(self.front), "back": list(self.back)}
