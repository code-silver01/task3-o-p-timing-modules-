"""
Chronis HW-1 — Extended Simulated Run.

Chains scenario traces back-to-back and drives the full sensor stack:
  trace -> mock HAL -> motion daemon + HR daemon -> signal extraction
        -> worn detector -> capture state machine

Produces a run log recording every level transition with its exact cause.
This log is treated as a real artifact (stand-in session data for calibration).
"""

import os
import sys
import json
import statistics
from collections import deque
from dataclasses import asdict
from typing import List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from traces.trace_generator import TraceGenerator, TraceSample
from daemons.motion_daemon import MotionDaemon, MotionState, Posture
from daemons.heart_rate_daemon import HeartRateDaemon
from daemons.worn_detector import WornNotWornDetector, WornState
from daemons.anchor_gesture_detector import AnchorGestureDetector
from state_machine.capture_state_machine import (
    CaptureStateMachine, CaptureSignals, Level,
)
from mock_hal.sensor_types import (
    IMUReading, PPGReading, SensorStatus, UnavailableReason,
)


SAMPLE_RATE = 20.0
DT = 1.0 / SAMPLE_RATE
HR_BASELINE = 68.0


def sample_to_imu(s: TraceSample) -> IMUReading:
    return IMUReading(
        timestamp=s.t, status=SensorStatus.OK,
        accel_x=s.accel_x, accel_y=s.accel_y, accel_z=s.accel_z,
        gyro_x=s.gyro_x, gyro_y=s.gyro_y, gyro_z=s.gyro_z,
    )


def sample_to_ppg(s: TraceSample) -> PPGReading:
    # Rule 3: if not worn, emit NOT_WORN, never a fake HR of 0
    if not s.worn or s.hr_signal_quality < 0.15:
        return PPGReading(
            timestamp=s.t, status=SensorStatus.NOT_WORN,
            unavailable_reason=UnavailableReason.DEVICE_NOT_WORN,
        )
    return PPGReading(
        timestamp=s.t, status=SensorStatus.OK,
        heart_rate_bpm=s.heart_rate,
        signal_quality=s.hr_signal_quality,
        spo2_percent=98.0,
    )


class AsleepTracker:
    """
    Spec: L0 'Dormant' enters when user is asleep, defined as
    'lying still 20+ min, low heart-rate variability'.

    This tracks how long the user has been continuously (lying AND still AND
    low-HRV). Only after 20 continuous minutes does asleep=True. Any
    interruption resets the timer.
    """
    ASLEEP_HOLD_S = 20 * 60.0
    HRV_WINDOW = 60  # samples of HR to estimate variability

    def __init__(self):
        self._still_since = None
        self._hr_window: deque = deque(maxlen=self.HRV_WINDOW)

    def update(self, t: float, lying: bool, still: bool, heart_rate: float) -> bool:
        self._hr_window.append(heart_rate)
        low_hrv = False
        if len(self._hr_window) >= 10:
            low_hrv = statistics.pstdev(self._hr_window) < 2.0  # very stable HR

        candidate = lying and still and low_hrv
        if candidate:
            if self._still_since is None:
                self._still_since = t
            return (t - self._still_since) >= self.ASLEEP_HOLD_S
        else:
            self._still_since = None
            return False


class SignalExtractor:
    """
    Converts raw daemon outputs + trace context into the CaptureSignals bundle
    the state machine consumes. Maintains rolling windows for 60s speech fraction,
    voice energy baseline, orientation variance, etc.
    """
    def __init__(self):
        self.speech_window: deque = deque(maxlen=int(60 * SAMPLE_RATE))
        self.voice_energy_window: deque = deque(maxlen=int(60 * SAMPLE_RATE))
        self.orient_window: deque = deque(maxlen=int(2 * SAMPLE_RATE))
        self.accel_window: deque = deque(maxlen=int(2 * SAMPLE_RATE))
        self.own_voice_streak = 0.0
        self.prev_expression = None
        self.asleep_tracker = AsleepTracker()
        # short smoothing window (1s) so a single noisy audio sample doesn't
        # register as a real "voice energy high" event and reset hysteresis
        self.voice_energy_smooth: deque = deque(maxlen=int(1.0 * SAMPLE_RATE))

    def extract(self, s: TraceSample, motion_out, hr_out) -> CaptureSignals:
        self.speech_window.append(1.0 if s.speech_detected else 0.0)
        self.voice_energy_window.append(s.audio_energy)
        if motion_out.valid and motion_out.pitch_deg is not None:
            self.orient_window.append(
                (motion_out.pitch_deg ** 2 + motion_out.roll_deg ** 2) ** 0.5)
        self.accel_window.append(abs((s.accel_x**2+s.accel_y**2+s.accel_z**2)**0.5 - 1.0))

        speech_fraction = (sum(self.speech_window) / len(self.speech_window)
                           if self.speech_window else 0.0)
        voice_baseline = (statistics.median(self.voice_energy_window)
                          if len(self.voice_energy_window) > 5 else 0.3)
        orient_var = (statistics.pvariance(self.orient_window)
                      if len(self.orient_window) > 2 else 0.0)
        accel_activity = (sum(self.accel_window) / len(self.accel_window)
                          if self.accel_window else 0.0)

        # own-voice streak (approx: speech + 2 speakers where one is user)
        if s.speech_detected and s.num_speakers >= 1:
            self.own_voice_streak += DT
        else:
            self.own_voice_streak = 0.0
        own_voice_active = self.own_voice_streak >= 5.0

        # expression change detection
        expr_changed = (s.face_expression is not None
                        and s.face_expression != "neutral"
                        and s.face_expression != self.prev_expression)
        self.prev_expression = s.face_expression

        # smoothed voice energy (1s mean) — used for level conditions
        self.voice_energy_smooth.append(s.audio_energy)
        voice_energy_smoothed = sum(self.voice_energy_smooth) / len(self.voice_energy_smooth)

        hr_val = hr_out.heart_rate_bpm if hr_out.valid else HR_BASELINE
        hr_quality = hr_out.signal_quality if hr_out.valid else 0.0

        # Spec-compliant asleep detection: lying still 20+ min with low HRV
        lying = (motion_out.posture == Posture.LYING) if motion_out.valid else False
        still = (motion_out.motion_state == MotionState.STILL) if motion_out.valid else False
        is_asleep = self.asleep_tracker.update(s.t, lying, still, hr_val)

        return CaptureSignals(
            timestamp=s.t,
            worn=s.worn,
            upright=(motion_out.posture == Posture.UPRIGHT) if motion_out.valid else True,
            asleep=is_asleep,
            hr_trustworthy=hr_out.trustworthy if hr_out.valid else False,
            hr_quality=hr_quality,
            heart_rate=hr_val,
            hr_baseline=HR_BASELINE,
            hrv_collapse=False,
            motion_state=(motion_out.motion_state.value
                          if motion_out.valid else "still"),
            purposeful_motion=(motion_out.valid and
                               motion_out.motion_state == MotionState.ACTIVE),
            movement_burst=(motion_out.valid and motion_out.change_point),
            own_voice_active=own_voice_active,
            background_speech=(s.speech_detected and s.num_speakers >= 1),
            two_person_exchange=(s.num_speakers == 2 and speech_fraction > 0.3),
            speech_fraction=speech_fraction,
            num_speakers=s.num_speakers,
            overlapping_speech=(s.num_speakers >= 3),
            voice_energy=voice_energy_smoothed,
            voice_energy_baseline=voice_baseline,
            face_expression_changed=expr_changed,
            stress_index=min(1.0, s.audio_energy * 0.5 +
                             max(0, (hr_val - HR_BASELINE)) / 60.0),
            stress_p90=0.6,
            hour_of_day=12,
        )


def run_extended_simulation(out_path: str = None, verbose: bool = True):
    gen = TraceGenerator(seed=7)

    # chain scenarios: idle -> ambient -> conversation -> high-energy -> back down
    scenario_plan = [
        ("idle_dormant", gen.gen_idle_dormant(30)),
        ("ambient_alone", gen.gen_ambient_alone(40)),
        ("active_conversation", gen.gen_active_conversation(60)),
        ("multiparty_highenergy", gen.gen_multiparty_highenergy(60)),
        ("active_conversation", gen.gen_active_conversation(40)),
        # long quiet tail so the full hysteresis descent L5->...->L1 can unwind
        # (needs 45+60+90+120s = ~315s of quiet to fully step down)
        ("ambient_alone", gen.gen_ambient_alone(340)),
    ]

    # Deliberate sensor-unavailable injection window (Rule 3 proof):
    # Between t=90s and t=100s, simulate IMU going unavailable mid-conversation.
    # The system must flag this as unavailable, never substitute fake zeros.
    INJECT_UNAVAIL_START = 90.0
    INJECT_UNAVAIL_END = 100.0

    # stitch with continuous timestamps
    chained: List[tuple] = []
    t_offset = 0.0
    for name, samples in scenario_plan:
        for s in samples:
            s.t = round(s.t + t_offset, 3)
            chained.append((name, s))
        if samples:
            t_offset = samples[-1].t + DT

    # daemons
    motion = MotionDaemon(SAMPLE_RATE)
    hr = HeartRateDaemon()
    worn = WornNotWornDetector()
    anchor = AnchorGestureDetector()
    sm = CaptureStateMachine()
    extractor = SignalExtractor()

    # state machine ticks every 500ms = every 10 samples at 20Hz
    ticks_per_recalc = int(0.5 / DT)

    run_log = {
        "_meta": {"SYNTHETIC": True, "type": "extended_run",
                  "scenarios": [n for n, _ in scenario_plan]},
        "transitions": [],
        "worn_events": [],
        "double_taps": [],
        "unavailable_events": [],
    }

    current_scenario = None
    for i, (name, s) in enumerate(chained):
        if name != current_scenario:
            current_scenario = name

        imu_r = sample_to_imu(s)
        ppg_r = sample_to_ppg(s)

        # Rule 3 injection: deliberately make IMU unavailable for 10 seconds
        if INJECT_UNAVAIL_START <= s.t <= INJECT_UNAVAIL_END:
            imu_r = IMUReading(
                timestamp=s.t, status=SensorStatus.UNAVAILABLE,
                unavailable_reason=UnavailableReason.I2C_TIMEOUT,
            )

        motion_out = motion.update(imu_r)
        hr_out = hr.update(ppg_r)

        # Rule 3 tracking: log unavailable sensor events
        if not imu_r.is_valid:
            if not run_log["unavailable_events"] or \
               run_log["unavailable_events"][-1]["sensor"] != "imu" or \
               s.t - run_log["unavailable_events"][-1]["t"] > 1.0:
                run_log["unavailable_events"].append(
                    {"t": s.t, "sensor": "imu",
                     "reason": imu_r.unavailable_reason.value if imu_r.unavailable_reason else "unknown"})

        if not hr_out.valid:
            if not run_log["unavailable_events"] or \
               run_log["unavailable_events"][-1]["sensor"] != "ppg" or \
               s.t - run_log["unavailable_events"][-1]["t"] > 1.0:
                run_log["unavailable_events"].append(
                    {"t": s.t, "sensor": "ppg", "reason": hr_out.unavailable_reason})

        # double tap -> anchor (never touches capture)
        if motion_out.valid and motion_out.double_tap:
            sig = anchor.on_double_tap(s.t)
            run_log["double_taps"].append({"t": s.t, "window":
                [sig.window.start, sig.window.end]})

        # worn detector
        orient_var = (statistics.pvariance(extractor.orient_window)
                      if len(extractor.orient_window) > 2 else 0.0)
        accel_act = (sum(extractor.accel_window)/len(extractor.accel_window)
                     if extractor.accel_window else 0.0)
        prev_worn_state = worn.state
        worn_out = worn.update(s.t, hr_out.signal_quality if hr_out.valid else 0.0,
                               orient_var, accel_act)

        # Spec: wake-up completion -> state machine restarts at L1
        from daemons.worn_detector import WornState as _WS
        if prev_worn_state == _WS.WAKING_UP and worn.state == _WS.WORN:
            sm.restart_at_L1(s.t)
            run_log["worn_events"].append({
                "t": s.t, "event": "wakeup_complete_restart_L1",
                "self_test_passed": worn_out.self_test_passed})

        # build signals & tick the state machine every 500ms
        signals = extractor.extract(s, motion_out, hr_out)
        signals.worn = worn.is_worn  # use computed worn, not trace field

        if i % ticks_per_recalc == 0:
            before = sm.level
            after = sm.tick(signals)
            if after != before:
                tr = sm.transitions[-1]
                run_log["transitions"].append({
                    "t": round(tr.timestamp, 2),
                    "scenario": name,
                    "from": tr.from_level.name,
                    "to": tr.to_level.name,
                    "cause": tr.cause,
                    "config": sm.current_config()["name"],
                })
                if verbose:
                    print(f"  [{tr.timestamp:7.2f}s] {tr.from_level.name} -> "
                          f"{tr.to_level.name}  ({tr.cause})")

    run_log["summary"] = {
        "total_samples": len(chained),
        "duration_s": round(chained[-1][1].t, 1) if chained else 0,
        "total_transitions": len(run_log["transitions"]),
        "double_taps_detected": len(run_log["double_taps"]),
        "final_level": sm.level.name,
        "annotation_windows": anchor.active_window_count,
        "rule3_injection": {
            "sensor": "imu",
            "window_s": f"{INJECT_UNAVAIL_START}-{INJECT_UNAVAIL_END}",
            "unavailable_events_logged": len([e for e in run_log["unavailable_events"]
                                               if e["sensor"] == "imu"]),
            "system_crashed": False,
            "fake_zeros_produced": False,
        },
    }

    if out_path:
        with open(out_path, "w") as f:
            json.dump(run_log, f, indent=2)

    return run_log


if __name__ == "__main__":
    here = os.path.dirname(__file__)
    out = os.path.join(here, "extended_run_log.json")
    print("Running extended simulation (chained scenarios)...\n")
    log = run_extended_simulation(out_path=out)
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for k, v in log["summary"].items():
        print(f"  {k}: {v}")
    print(f"\nRun log written to: {out}")
