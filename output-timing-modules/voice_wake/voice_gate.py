"""
Chronis Task 3, Team B, Day 3 — Voice-Gated Wake.

A real voice-ID system would compute a neural embedding from audio. This
mock stands that in with a plain list of numbers (a "fingerprint") — the
actual math (comparing two numbers-lists for closeness) is the same idea
a real embedding comparison uses, just without the neural network. That
keeps this fully testable with no audio, no model, no hardware.
"""

import math
from typing import List, Optional

# How close two fingerprints must be to count as "the same voice". Chosen
# so a slightly-noisy repeat of the SAME enrolled voice still matches, but
# a genuinely different voice does not — tuned against the two synthetic
# samples in this module's tests, not against real audio (there isn't any).
MATCH_THRESHOLD = 0.25


def _distance(a: List[float], b: List[float]) -> float:
    """Euclidean distance between two fingerprints — smaller means more
    similar. This is the simplest possible 'how alike are these two
    vectors' measure, which is enough to prove the GATE LOGIC works;
    swapping in a real embedding model later wouldn't change anything
    else in this file."""
    if len(a) != len(b):
        raise ValueError("fingerprints must be the same length to compare")
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


class NotEnrolledError(Exception):
    """Raised if something tries to check a voice before any voice has
    been enrolled — there's nothing to match against yet."""
    pass


class VoiceGate:
    def __init__(self, match_threshold: float = MATCH_THRESHOLD):
        self._enrolled_fingerprint: Optional[List[float]] = None
        self.match_threshold = match_threshold

    @property
    def is_enrolled(self) -> bool:
        return self._enrolled_fingerprint is not None

    def enroll(self, fingerprint: List[float]):
        """Stores the fingerprint from a mock enrolled-voice sample at
        setup time. Spec's exact words: 'store a fingerprint/embedding at
        setup time' — this is that step."""
        self._enrolled_fingerprint = list(fingerprint)

    def matches_enrolled_voice(self, fingerprint: List[float]) -> bool:
        if not self.is_enrolled:
            raise NotEnrolledError("no voice has been enrolled yet — call enroll() first")
        return _distance(self._enrolled_fingerprint, fingerprint) <= self.match_threshold

    def trigger_wake(self, fingerprint: List[float], display_manager=None) -> bool:
        """The actual wake trigger. Returns whether it woke the display —
        and only actually calls the display's tap_to_wake() if the voice
        matched. A non-matching voice does nothing at all, on purpose:
        silence is the correct behavior for a stranger's voice, not an
        error or a partial wake."""
        matched = self.matches_enrolled_voice(fingerprint)
        if matched and display_manager is not None:
            display_manager.tap_to_wake()
        return matched