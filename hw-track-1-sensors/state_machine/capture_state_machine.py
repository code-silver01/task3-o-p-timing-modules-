"""
Chronis HW-1 — 6-Level Capture-Intensity State Machine.

The device is always in exactly one level L0..L5, recalculated every 500ms.
Each level dictates camera/audio behavior. Transitions UP use the exact rules
from the sprint doc; transitions DOWN use hysteresis timers to prevent flicker.

This is the "brain" that decides how much to capture moment-to-moment.

Inputs each tick (a CaptureSignals bundle):
  - worn (bool)
  - upright (bool)
  - hr_trustworthy (bool), hr_quality (0..1)
  - heart_rate, hr_baseline
  - motion_state, purposeful_motion (bool), movement_burst (bool)
  - own_voice_active (bool), background_speech (bool)
  - speech_fraction (0..1 over rolling 60s), num_speakers
  - voice_energy, voice_energy_baseline
  - face_expression_changed (bool)
  - stress_index, stress_p90
  - hour_of_day (int)
  - asleep (bool)
"""

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional, List
from collections import deque


class Level(IntEnum):
    L0 = 0  # Dormant
    L1 = 1  # Ambient
    L2 = 2  # Passive
    L3 = 3  # Active
    L4 = 4  # Engaged
    L5 = 5  # Peak


# Per-level capture configuration (what camera & audio do)
LEVEL_CONFIG = {
    Level.L0: {"name": "Dormant",  "camera_fps": 0,    "camera_comp": "off",
               "audio_rate": 8000,  "audio_saved": False, "audio_desc": "8kHz buffer only"},
    Level.L1: {"name": "Ambient",  "camera_fps": 0.5,  "camera_comp": "heavy",
               "audio_rate": 8000,  "audio_saved": True,  "audio_desc": "8kHz stereo saved"},
    Level.L2: {"name": "Passive",  "camera_fps": 1,    "camera_comp": "moderate",
               "audio_rate": 16000, "audio_saved": True,  "audio_desc": "16kHz continuous"},
    Level.L3: {"name": "Active",   "camera_fps": 10,   "camera_comp": "low",
               "audio_rate": 16000, "audio_saved": True,  "audio_desc": "16kHz full, speaker sep"},
    Level.L4: {"name": "Engaged",  "camera_fps": 30,   "camera_comp": "minimal",
               "audio_rate": 16000, "audio_saved": True,  "audio_desc": "16kHz dual-boosted"},
    Level.L5: {"name": "Peak",     "camera_fps": 30,   "camera_comp": "none",
               "audio_rate": 48000, "audio_saved": True,  "audio_desc": "48kHz lossless"},
}


@dataclass
class CaptureSignals:
    """All inputs the state machine reads each tick."""
    timestamp: float
    worn: bool = True
    upright: bool = True
    asleep: bool = False
    hr_trustworthy: bool = True
    hr_quality: float = 0.8
    heart_rate: float = 70.0
    hr_baseline: float = 68.0
    hrv_collapse: bool = False
    motion_state: str = "still"
    purposeful_motion: bool = False
    movement_burst: bool = False
    own_voice_active: bool = False
    background_speech: bool = False
    two_person_exchange: bool = False
    speech_fraction: float = 0.0        # fraction of last 60s with speech
    num_speakers: int = 0
    overlapping_speech: bool = False
    voice_energy: float = 0.0
    voice_energy_baseline: float = 0.3
    face_expression_changed: bool = False
    stress_index: float = 0.0
    stress_p90: float = 1.0
    hour_of_day: int = 12


@dataclass
class LevelTransition:
    timestamp: float
    from_level: Level
    to_level: Level
    cause: str


class CaptureStateMachine:
    """
    Implements the exact 6-level transition + hysteresis logic.
    Call tick(signals) every 500ms.
    """

    # hysteresis hold times (seconds) for stepping DOWN
    HYST_L5_L4 = 45.0
    HYST_L4_L3 = 60.0
    HYST_L3_L2 = 90.0
    HYST_L2_L1 = 120.0
    HYST_L1_L0_NOTWORN = 5 * 60.0

    def __init__(self):
        self.level = Level.L0
        self.transitions: List[LevelTransition] = []
        # timers: when did the down-condition first become continuously true
        self._down_timer_start: Optional[float] = None
        self._notworn_since: Optional[float] = None
        self._last_tick: Optional[float] = None

    # ---------- helper predicates ----------
    @staticmethod
    def _hr_above(sig: CaptureSignals, pct: float) -> bool:
        if sig.hr_baseline <= 0:
            return False
        return (sig.heart_rate - sig.hr_baseline) / sig.hr_baseline > pct

    @staticmethod
    def _hr_between(sig: CaptureSignals, lo: float, hi: float) -> bool:
        if sig.hr_baseline <= 0:
            return False
        r = (sig.heart_rate - sig.hr_baseline) / sig.hr_baseline
        return lo <= r <= hi

    # ---------- UP transitions ----------
    def _can_exit_L0(self, sig: CaptureSignals) -> bool:
        # upright + worn + HR signal quality above threshold
        return sig.worn and sig.upright and sig.hr_quality > 0.5 and not sig.asleep

    def _L1_to_L2(self, sig: CaptureSignals) -> Optional[str]:
        if sig.motion_state in ("walking", "active"):
            return "motion crossed threshold"
        if sig.background_speech:
            return "background speech detected 3m+ away"
        if self._hr_between(sig, 0.05, 0.10):
            return "heart rate 5-10% above baseline"
        if 8 <= sig.hour_of_day <= 22:
            return "time-of-day likelihood (8am-10pm)"
        return None

    def _L2_to_L3(self, sig: CaptureSignals) -> Optional[str]:
        if sig.own_voice_active:
            return "own voice detected 5s+"
        if sig.purposeful_motion:
            return "purposeful upper-body motion"
        if self._hr_above(sig, 0.15):
            return "heart rate >15% above baseline"
        if sig.two_person_exchange:
            return "clear two-person exchange"
        return None

    def _L3_to_L4(self, sig: CaptureSignals) -> Optional[str]:
        # ALL within same 60s window: speech >40%, >1 speaker, AND (HR>20% OR voice energy high)
        cond_speech = sig.speech_fraction > 0.40
        cond_speakers = sig.num_speakers > 1
        cond_arousal = (self._hr_above(sig, 0.20) or
                        sig.voice_energy > sig.voice_energy_baseline * 1.3)
        if cond_speech and cond_speakers and cond_arousal:
            return "L4: speech>40% + multi-speaker + arousal (all in 60s window)"
        return None

    def _L4_to_L5(self, sig: CaptureSignals) -> Optional[str]:
        # at least 3 of 6 conditions
        conds = {
            "voice energy far above avg": sig.voice_energy > sig.voice_energy_baseline * 1.8,
            "HR 30%+ or HRV collapse": self._hr_above(sig, 0.30) or sig.hrv_collapse,
            "rapid movement burst": sig.movement_burst,
            ">2 speakers overlapping": sig.num_speakers > 2 and sig.overlapping_speech,
            "expression change": sig.face_expression_changed,
            "stress above p90": sig.stress_index > sig.stress_p90,
        }
        active = [k for k, v in conds.items() if v]
        if len(active) >= 3:
            return f"L5: 3+ signals converge ({', '.join(active[:3])})"
        return None

    def _count_L5_conditions(self, sig: CaptureSignals) -> int:
        conds = [
            sig.voice_energy > sig.voice_energy_baseline * 1.8,
            self._hr_above(sig, 0.30) or sig.hrv_collapse,
            sig.movement_burst,
            sig.num_speakers > 2 and sig.overlapping_speech,
            sig.face_expression_changed,
            sig.stress_index > sig.stress_p90,
        ]
        return sum(conds)

    def _count_L4_conditions(self, sig: CaptureSignals) -> int:
        return sum([
            sig.speech_fraction > 0.40,
            sig.num_speakers > 1,
            self._hr_above(sig, 0.20),
            sig.voice_energy > sig.voice_energy_baseline * 1.3,
        ])

    def _count_L3_conditions(self, sig: CaptureSignals) -> int:
        return sum([
            sig.own_voice_active,
            sig.purposeful_motion,
            self._hr_above(sig, 0.15),
            sig.two_person_exchange,
        ])

    def _count_L2_conditions(self, sig: CaptureSignals) -> int:
        return sum([
            sig.motion_state in ("walking", "active"),
            sig.background_speech,
            self._hr_between(sig, 0.05, 0.10),
        ])

    # ---------- main tick ----------
    def tick(self, sig: CaptureSignals) -> Level:
        prev = self.level

        # not-worn timer for L1->L0
        if not sig.worn:
            if self._notworn_since is None:
                self._notworn_since = sig.timestamp
        else:
            self._notworn_since = None

        # Try to move UP first (one level per tick, cascade allowed via re-eval)
        moved = self._try_up(sig) or self._try_down(sig)

        self._last_tick = sig.timestamp
        return self.level

    def _emit(self, to: Level, cause: str, ts: float):
        self.transitions.append(
            LevelTransition(timestamp=ts, from_level=self.level, to_level=to, cause=cause))
        self.level = to
        self._down_timer_start = None  # reset hysteresis timer on any move

    def _try_up(self, sig: CaptureSignals) -> bool:
        lvl = self.level
        if lvl == Level.L0:
            if self._can_exit_L0(sig):
                self._emit(Level.L1, "L0 exit: upright+worn+HR quality ok", sig.timestamp)
                return True
        elif lvl == Level.L1:
            c = self._L1_to_L2(sig)
            if c:
                self._emit(Level.L2, c, sig.timestamp)
                return True
        elif lvl == Level.L2:
            c = self._L2_to_L3(sig)
            if c:
                self._emit(Level.L3, c, sig.timestamp)
                return True
        elif lvl == Level.L3:
            c = self._L3_to_L4(sig)
            if c:
                self._emit(Level.L4, c, sig.timestamp)
                return True
        elif lvl == Level.L4:
            c = self._L4_to_L5(sig)
            if c:
                self._emit(Level.L5, c, sig.timestamp)
                return True
        return False

    def _try_down(self, sig: CaptureSignals) -> bool:
        lvl = self.level

        # L1 -> L0 uses the not-worn 5-min timer specifically
        if lvl == Level.L1:
            if self._notworn_since is not None:
                if (sig.timestamp - self._notworn_since) >= self.HYST_L1_L0_NOTWORN:
                    self._emit(Level.L0, "L1->L0: not worn 5+ min", sig.timestamp)
                    return True
            # also drop to L0 if asleep
            if sig.asleep:
                self._emit(Level.L0, "L1->L0: user asleep", sig.timestamp)
                return True
            return False

        # For L2..L5, down-transition requires the level's UP-conditions to be
        # absent continuously for the hysteresis hold time.
        hold_map = {
            Level.L5: (self.HYST_L5_L4, self._count_L5_conditions, Level.L4, 1),
            Level.L4: (self.HYST_L4_L3, self._count_L4_conditions, Level.L3, 0),
            Level.L3: (self.HYST_L3_L2, self._count_L3_conditions, Level.L2, 0),
            Level.L2: (self.HYST_L2_L1, self._count_L2_conditions, Level.L1, 0),
        }
        if lvl not in hold_map:
            return False

        hold_s, counter, target, floor = hold_map[lvl]
        active = counter(sig)

        # L5 special: holds as long as 2+ conditions active; steps down after
        # 45s with 1 or fewer. Others: step down after hold with none active
        # (L5 floor=1 means "1 or fewer"; others floor=0 means "none").
        down_ok = active <= floor

        if down_ok:
            if self._down_timer_start is None:
                self._down_timer_start = sig.timestamp
            elif (sig.timestamp - self._down_timer_start) >= hold_s:
                self._emit(target, f"{lvl.name}->{target.name}: "
                                   f"hysteresis {hold_s:.0f}s with <= {floor} conditions",
                           sig.timestamp)
                return True
        else:
            self._down_timer_start = None  # condition re-appeared, reset
        return False

    def restart_at_L1(self, timestamp: float):
        """
        Spec requirement: after the worn detector completes its 15-second
        wake-up, the state machine restarts at L1 and re-assesses upward —
        it must NOT snap back to whatever level it was at before the device
        was taken off.
        """
        if self.level != Level.L1:
            self._emit(Level.L1, "wake-up complete: restart at L1 (spec)", timestamp)
        self._down_timer_start = None
        self._notworn_since = None

    def current_config(self) -> dict:
        return LEVEL_CONFIG[self.level]
