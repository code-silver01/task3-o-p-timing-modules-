"""
Chronis Task 3, Team B, Day 2 — OLED Display Manager.

Design decision, stated up front: unlike Day 1's LED controller (one
active state at a time), the display manager tracks a SET of "things
currently wanting to show" (self._active). Why the difference: several
of these genuinely can be true at once in real life — the device can be
charging AND have a pending insight notification AND be mid-capture, all
simultaneously. The screen still only shows ONE of them (there's only one
screen), so we need the ranked list from oled_states.py to pick a winner
— but the underlying truth ("what's actually going on right now") is a
set, not a single value. Clearing charging shouldn't clear the pending
insight notification underneath it.
"""

from .oled_states import (
    DisplayState, PRIORITY_ORDER, FORCE_FULL_BRIGHTNESS,
    INSIGHT_MAX_CHARS, INSIGHT_AUTO_DISMISS_SECONDS, TAP_TO_WAKE_SECONDS,
    AMBIENT_BRIGHTNESS_CDM2, AMBIENT_DOT_CYCLE_SECONDS, AMBIENT_DOT_STATES,
)
from .mock_display_buffer import MockDisplayBuffer

FULL_BRIGHTNESS_CDM2 = 400.0   # a plausible normal OLED-awake brightness for this mock


class InsightTooLongError(Exception):
    pass


class CameraKilledIconLockedError(Exception):
    """Raised if code tries to clear the camera-killed icon any way other
    than the dedicated physical-slider-reset method."""
    pass


class OLEDDisplayManager:
    def __init__(self, buffer: MockDisplayBuffer):
        self.buffer = buffer
        self._active = set()
        self._camera_active = False       # the ONLY thing that drives the privacy pixel
        self._insight_message = None
        self._insight_requested_at = None
        self._insight_expanded = False
        self._awake_until = -1
        self._clock = 0                   # mock seconds, advanced only by tick()
        self._settings = {}               # generic cosmetic settings — see note below
        self._watchface = "default"
        self._render()

    # ---- event-driven inputs ----

    def request(self, state: DisplayState, message: str = None):
        if state == DisplayState.INSIGHT_NOTIFICATION:
            if message is None or len(message) > INSIGHT_MAX_CHARS:
                raise InsightTooLongError(
                    f"insight message must be <= {INSIGHT_MAX_CHARS} chars, "
                    f"got {0 if message is None else len(message)}")
            self._insight_message = message
            self._insight_requested_at = self._clock
            self._insight_expanded = False
        self._active.add(state)
        self._render()

    def clear(self, state: DisplayState):
        if state == DisplayState.CAMERA_KILLED_ICON:
            raise CameraKilledIconLockedError(
                "camera-killed icon can only be cleared via reset_camera_kill_icon() "
                "— it models a physical slider, not a software toggle")
        self._active.discard(state)
        self._render()

    def reset_camera_kill_icon(self):
        """The one legitimate way CAMERA_KILLED_ICON goes away — stands in
        for the user physically moving the kill-switch slider back."""
        self._active.discard(DisplayState.CAMERA_KILLED_ICON)
        self._render()

    def expand_insight(self):
        self._insight_expanded = True
        self._render()

    def set_camera_active(self, is_active: bool):
        """This is the ONLY method anywhere in this class that changes
        privacy-pixel visibility. It exists to be called by the camera
        subsystem itself (a real device would call this from the actual
        capture daemon) — not exposed as a user preference."""
        self._camera_active = is_active
        self._render()

    def tap_to_wake(self):
        self._awake_until = self._clock + TAP_TO_WAKE_SECONDS
        self._render()

    def tick(self, seconds: float):
        """Advances the mock clock. No real datetime involved, same
        reasoning as Day 1's mock hour — deterministic tests, not
        'whatever time it happens to be when you run pytest'."""
        self._clock += seconds
        if (DisplayState.INSIGHT_NOTIFICATION in self._active
                and self._insight_requested_at is not None
                and self._clock - self._insight_requested_at >= INSIGHT_AUTO_DISMISS_SECONDS):
            self._active.discard(DisplayState.INSIGHT_NOTIFICATION)
        self._render()

    # ---- the settings/watchface surfaces the privacy-pixel test tries to abuse ----

    def apply_display_setting(self, key: str, value):
        """A generic-looking cosmetic settings store — brightness curve
        preferences, clock format, that kind of thing. Deliberately NOT
        consulted anywhere in _render()'s privacy-pixel line, no matter
        what key gets thrown at it — see test_privacy_pixel.py for the
        proof this can't be used to hide the pixel."""
        self._settings[key] = value

    def set_watchface(self, name: str):
        """Same idea — a custom watchface name is stored, but never once
        read when computing privacy_pixel_on."""
        self._watchface = name

    # ---- internal ----

    def _current_priority_state(self) -> DisplayState:
        for state in PRIORITY_ORDER:
            if state in self._active:
                return state
        return DisplayState.IDLE_FACE

    def _is_awake(self) -> bool:
        return self._clock < self._awake_until

    def _render(self):
        state = self._current_priority_state()

        # Privacy pixel: computed from exactly one source, every single
        # time, regardless of every other branch below. This line is the
        # entire guarantee — it never reads self._settings or
        # self._watchface, so there is no code path through those two
        # surfaces that can change it.
        privacy_pixel_on = self._camera_active

        if state in FORCE_FULL_BRIGHTNESS:
            content = self._content_for(state)
            self.buffer.set_frame(content, FULL_BRIGHTNESS_CDM2, privacy_pixel_on)
            return

        if self._is_awake():
            content = self._content_for(state)
            self.buffer.set_frame(content, FULL_BRIGHTNESS_CDM2, privacy_pixel_on)
            return

        # ambient mode — low brightness, cycling status dot, regardless
        # of which lower-priority state is technically "active"
        dot_index = int(self._clock // AMBIENT_DOT_CYCLE_SECONDS) % len(AMBIENT_DOT_STATES)
        content = {"mode": "ambient", "dot": AMBIENT_DOT_STATES[dot_index]}
        self.buffer.set_frame(content, AMBIENT_BRIGHTNESS_CDM2, privacy_pixel_on)

    def _content_for(self, state: DisplayState) -> dict:
        if state == DisplayState.INSIGHT_NOTIFICATION:
            return {
                "state": state.value,
                "message": self._insight_message,
                "expanded": self._insight_expanded,
            }
        return {"state": state.value}