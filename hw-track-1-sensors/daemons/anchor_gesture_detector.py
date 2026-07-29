"""
Chronis HW-1 — Anchor Gesture Detector.

A double-tap is PURELY an annotation marker. The sprint doc is explicit and
warns this is easy to get wrong:

  - It does NOT start recording
  - It does NOT change the capture-intensity level
  - It does NOT trigger a camera burst

All it does:
  1. Open a 30-second annotation window around the tap's timestamp
  2. Emit a "moment marked" signal for the phone app

This module is deliberately isolated from any capture-state code so the
distinction is enforced structurally, not just by convention.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Callable


@dataclass
class AnnotationWindow:
    """A 30-second window around a marked moment."""
    center_timestamp: float
    start: float
    end: float
    note: Optional[str] = None  # filled later when phone sends a note

    def contains(self, t: float) -> bool:
        return self.start <= t <= self.end


@dataclass
class MomentMarkedSignal:
    """The only thing that leaves this module toward the phone app."""
    timestamp: float
    window: AnnotationWindow
    message: str = "moment_marked"


class AnchorGestureDetector:
    """
    Receives double-tap events (already detected by the motion daemon) and
    turns them into annotation windows. This class has NO reference to and NO
    ability to change capture state — that's the whole point.
    """

    WINDOW_SECONDS = 30.0

    def __init__(self, phone_notifier: Optional[Callable[[MomentMarkedSignal], None]] = None):
        self.windows: List[AnnotationWindow] = []
        self._phone_notifier = phone_notifier
        self._signals_emitted: List[MomentMarkedSignal] = []

    def on_double_tap(self, timestamp: float) -> MomentMarkedSignal:
        """
        Handle a detected double-tap. Opens a 30s window centered on the tap
        (15s before, 15s after) and emits a phone signal.

        Returns the signal. Does NOT return or touch any capture state.
        """
        half = self.WINDOW_SECONDS / 2.0
        window = AnnotationWindow(
            center_timestamp=timestamp,
            start=timestamp - half,
            end=timestamp + half,
        )
        self.windows.append(window)

        signal = MomentMarkedSignal(timestamp=timestamp, window=window)
        self._signals_emitted.append(signal)

        if self._phone_notifier:
            self._phone_notifier(signal)

        return signal

    def attach_note(self, timestamp: float, note: str) -> bool:
        """
        Phone sends back a text note; attach it to the nearest window whose
        span contains this timestamp (or the closest center).
        """
        # prefer a window that contains the timestamp
        for w in self.windows:
            if w.contains(timestamp):
                w.note = note
                return True
        # else attach to nearest center
        if not self.windows:
            return False
        nearest = min(self.windows, key=lambda w: abs(w.center_timestamp - timestamp))
        nearest.note = note
        return True

    @property
    def active_window_count(self) -> int:
        return len(self.windows)

    @property
    def signals(self) -> List[MomentMarkedSignal]:
        return list(self._signals_emitted)
