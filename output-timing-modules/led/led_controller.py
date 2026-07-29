"""
Chronis Task 3, Team B, Day 1 — LED Controller (the state machine).

Design decision worth stating up front: this models the LEDs as ONE active
state at a time, not many independent layers stacked together. The task
title is literally "LED Controller: Full State Machine" — a state machine
by definition is "one state active at a time, with rules for moving
between states" — so trigger(new_state) simply replaces whatever was
showing before. This is a real simplification (real firmware might want
the back-zone amber breathing running WHILE the front arc shows a sync
chase, at the same time) — noted here rather than hidden, because it's
the kind of thing worth a second look once real hardware exists.
"""

from .led_states import LEDState, UNSUPPRESSIBLE
from .mock_led_driver import MockLEDDriver, NUM_FRONT, NUM_BACK


class CannotSuppressError(Exception):
    """Raised when code tries to suppress tamper-alert or kill-switch-
    confirmation. These two must always be able to reach the user."""
    pass


# Full brightness for an "on" LED in our mock world.
FULL = 255
# What "dimmed" (10pm-11pm window) looks like — noticeably lower, not off.
DIM_SCALE = 0.3


class LEDController:
    def __init__(self, driver: MockLEDDriver,
                 dim_start_hour: int = 22, full_off_start_hour: int = 23,
                 night_end_hour: int = 7):
        """
        dim_start_hour / full_off_start_hour come directly from the spec
        (10pm / 11pm). night_end_hour does NOT — the spec never states
        what time LEDs resume normal brightness in the morning, so this
        is an assumption, defaulted to 7am and made a constructor
        argument specifically so it's visible and overridable rather than
        a hidden magic number buried in the logic.
        """
        self.driver = driver
        self.current_state = LEDState.IDLE_OFF
        self._suppressed = set()
        self._charging = False
        self._hour = 12  # mock clock — tests set this directly, no real time involved
        self.dim_start_hour = dim_start_hour
        self.full_off_start_hour = full_off_start_hour
        self.night_end_hour = night_end_hour

    # ---- user-facing controls ----

    def suppress(self, state: LEDState):
        if state in UNSUPPRESSIBLE:
            raise CannotSuppressError(
                f"{state.value} cannot be suppressed — it is a safety-critical alert")
        self._suppressed.add(state)

    def unsuppress(self, state: LEDState):
        self._suppressed.discard(state)

    def is_suppressed(self, state: LEDState) -> bool:
        return state in self._suppressed

    def set_time(self, hour: int):
        """Mock clock setter. 0-23. No real datetime involved on purpose —
        a test that depends on the actual wall-clock hour would pass or
        fail differently depending on when you happen to run it, which is
        exactly the kind of flaky test Day 2 of Task 2 already taught us
        to avoid (MockFleet's fixed random seed was the same idea)."""
        if not (0 <= hour <= 23):
            raise ValueError("hour must be 0-23")
        self._hour = hour

    def set_charging(self, is_charging: bool):
        self._charging = is_charging

    # ---- the state machine itself ----

    def trigger(self, state: LEDState):
        """Move the state machine into `state` and immediately push the
        resulting pattern to the driver — mirrors how a real event
        (battery low, tamper detected, etc.) would immediately update
        what's on screen, not wait for some later render call."""
        self.current_state = state
        self._render()

    def update_capture_indicator(self, cse_level: int):
        """The one state that isn't triggered by a one-off event — it
        tracks the CSE's current level continuously. L4/L5 -> dim dot.
        L3 and below -> nothing (this is just IDLE_OFF; the spec's 'no
        LED at all' IS the idle state, not a distinct visual style)."""
        if cse_level >= 4:
            self.trigger(LEDState.CAPTURE_ACTIVE_DIM)
        else:
            self.trigger(LEDState.IDLE_OFF)

    # ---- internal: sleep schedule + suppression + rendering ----

    def _night_phase(self) -> str:
        """Returns 'normal', 'dim', or 'off' purely from the mock hour —
        charging override is handled by the caller, not here, so this
        function answers ONE question only: what does the clock say."""
        h = self._hour
        if h >= self.full_off_start_hour or h < self.night_end_hour:
            return "off"
        if h >= self.dim_start_hour:
            return "dim"
        return "normal"

    def _pattern_for(self, state: LEDState):
        """The actual LED pattern for each state. Because this is a mock
        driver (not real hardware timing), these patterns represent ONE
        recognizable frame of each animation, not a full animated
        sequence — enough to prove 'the right state produces the right
        kind of output', which is what a test can actually check."""
        front = [0] * NUM_FRONT
        back = [0] * NUM_BACK

        if state == LEDState.CHARGING_FILL:
            front = [FULL] * NUM_FRONT
        elif state == LEDState.SYNC_CHASE:
            front[0] = FULL
        elif state == LEDState.LOW_BATTERY_PULSE:
            front = [80] * NUM_FRONT
        elif state == LEDState.NEW_INSIGHT_FLASH:
            front = [FULL] * NUM_FRONT
        elif state == LEDState.NOT_WORN_BREATHING_AMBER:
            back = [120] * NUM_BACK
        elif state == LEDState.KILL_SWITCH_CONFIRMATION_FLASH:
            front = [FULL] * NUM_FRONT
            back = [FULL] * NUM_BACK
        elif state == LEDState.TAMPER_ALERT_PULSE:
            front = [FULL] * NUM_FRONT
            back = [FULL] * NUM_BACK
        elif state == LEDState.BLE_PAIRING_CHASE:
            front[0] = FULL
        elif state == LEDState.MODE_CHANGE_CONFIRMATION_FLASH:
            front = [200] * NUM_FRONT
        elif state == LEDState.CAPTURE_ACTIVE_DIM:
            front[0] = 40
        elif state == LEDState.IDLE_OFF:
            pass  # already all zeros

        return front, back

    def _render(self):
        state = self.current_state

        # Safety-critical states bypass EVERYTHING below — suppression
        # AND the night schedule. A tamper alert dimmed away at 2am
        # because "it's night mode" would defeat the entire point of it
        # being unsuppressible.
        if state in UNSUPPRESSIBLE:
            front, back = self._pattern_for(state)
            self.driver.set_front(front)
            self.driver.set_back(back)
            return

        if state in self._suppressed:
            self.driver.set_front([0] * NUM_FRONT)
            self.driver.set_back([0] * NUM_BACK)
            return

        front, back = self._pattern_for(state)

        if not self._charging:
            phase = self._night_phase()
            if phase == "off":
                front = [0] * NUM_FRONT
                back = [0] * NUM_BACK
            elif phase == "dim":
                front = [int(v * DIM_SCALE) for v in front]
                back = [int(v * DIM_SCALE) for v in back]
            # phase == "normal": no change

        self.driver.set_front(front)
        self.driver.set_back(back)
