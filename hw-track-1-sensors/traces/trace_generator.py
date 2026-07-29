"""
Chronis HW-1 — Synthetic Sensor Trace Generator.

Generates realistic fake sensor data for 4 scenarios. Each trace is a time series
that daemon logic can be tested against without a real body wearing a real device.

Scenarios:
  1. idle_dormant        — device off-body or user asleep
  2. ambient_alone       — worn, quiet, no one around
  3. active_conversation — user talking with one other person
  4. multiparty_highenergy — several people, animated exchange

Every trace is clearly labeled synthetic. Values are grounded in realistic ranges:
  - resting HR ~60-70 bpm, active ~90-120, peak ~130+
  - accel magnitude ~1g at rest, spikes to 1.5-2g on movement
  - audio energy 0.0 (silent) to 1.0 (loud animated speech)
"""

import json
import math
import random
import os
from dataclasses import dataclass, asdict
from typing import List, Optional


@dataclass
class TraceSample:
    """One time-step of synthetic sensor data."""
    t: float                # seconds from start
    accel_x: float
    accel_y: float
    accel_z: float
    gyro_x: float
    gyro_y: float
    gyro_z: float
    heart_rate: float
    hr_signal_quality: float
    audio_energy: float
    speech_detected: bool
    num_speakers: int
    worn: bool              # ground-truth worn state (for validation)
    # optional event markers
    double_tap: bool = False
    face_detected: bool = False
    face_expression: Optional[str] = None


class TraceGenerator:
    """Generates labeled synthetic sensor traces."""

    def __init__(self, sample_rate_hz: float = 20.0, seed: int = 42):
        """
        sample_rate_hz: how many samples per second (IMU-driven, 20Hz is realistic)
        seed: for reproducible traces
        """
        self.dt = 1.0 / sample_rate_hz
        self.rng = random.Random(seed)

    def _n(self, sigma: float) -> float:
        """Gaussian noise helper."""
        return self.rng.gauss(0, sigma)

    # -----------------------------------------------------
    # Scenario 1: Idle / Dormant
    # -----------------------------------------------------
    def gen_idle_dormant(self, duration_s: float = 60.0) -> List[TraceSample]:
        """
        Device off-body OR user asleep.
        - Lying flat (accel_z low, accel_x or y ~1g if on a surface)
        - Almost no motion
        - Low, stable heart rate variability (asleep) OR no HR (off-body)
        - Silent
        """
        samples = []
        n = int(duration_s / self.dt)
        # Device lying on its side on a table: gravity on x-axis
        for i in range(n):
            t = i * self.dt
            samples.append(TraceSample(
                t=round(t, 3),
                accel_x=1.0 + self._n(0.005),   # gravity on x (lying down)
                accel_y=0.0 + self._n(0.005),
                accel_z=0.0 + self._n(0.005),
                gyro_x=self._n(0.1),
                gyro_y=self._n(0.1),
                gyro_z=self._n(0.1),
                heart_rate=58.0 + self._n(0.5),  # low, very stable (sleep)
                hr_signal_quality=0.9 + self._n(0.02),
                audio_energy=max(0.0, 0.02 + self._n(0.01)),
                speech_detected=False,
                num_speakers=0,
                worn=True,  # asleep but still worn
            ))
        return samples

    # -----------------------------------------------------
    # Scenario 2: Ambient Alone
    # -----------------------------------------------------
    def gen_ambient_alone(self, duration_s: float = 60.0) -> List[TraceSample]:
        """
        Worn, upright, quiet, alone. Occasional small movements.
        - Upright (gravity on z)
        - Resting HR ~68
        - Very low audio, no speech
        """
        samples = []
        n = int(duration_s / self.dt)
        for i in range(n):
            t = i * self.dt
            # occasional small shifts (shifting weight, small gestures)
            moving = self.rng.random() < 0.03
            move_amt = 0.15 if moving else 0.02
            samples.append(TraceSample(
                t=round(t, 3),
                accel_x=self._n(move_amt),
                accel_y=self._n(move_amt),
                accel_z=1.0 + self._n(move_amt),  # upright
                gyro_x=self._n(3.0 if moving else 0.3),
                gyro_y=self._n(3.0 if moving else 0.3),
                gyro_z=self._n(3.0 if moving else 0.3),
                heart_rate=68.0 + self._n(1.5),
                hr_signal_quality=0.85 + self._n(0.05),
                audio_energy=max(0.0, 0.08 + self._n(0.03)),
                speech_detected=False,
                num_speakers=0,
                worn=True,
            ))
        return samples

    # -----------------------------------------------------
    # Scenario 3: Active Conversation
    # -----------------------------------------------------
    def gen_active_conversation(self, duration_s: float = 60.0) -> List[TraceSample]:
        """
        User talking with one other person. Purposeful motion, elevated HR,
        speech present, 2 speakers alternating.
        """
        samples = []
        n = int(duration_s / self.dt)
        # baseline HR rises over first 10s then holds elevated
        for i in range(n):
            t = i * self.dt
            # who's speaking alternates every ~4s
            speaking_block = int(t / 4) % 2  # 0 = user, 1 = other
            speech = self.rng.random() < 0.7  # 70% speech density
            # gesture motion while talking
            gesture = self.rng.random() < 0.15
            move_amt = 0.25 if gesture else 0.06

            hr_ramp = min(1.0, t / 10.0)
            hr = 68.0 + (18.0 * hr_ramp)  # rises to ~86

            samples.append(TraceSample(
                t=round(t, 3),
                accel_x=self._n(move_amt),
                accel_y=self._n(move_amt),
                accel_z=1.0 + self._n(move_amt),
                gyro_x=self._n(8.0 if gesture else 1.0),
                gyro_y=self._n(8.0 if gesture else 1.0),
                gyro_z=self._n(8.0 if gesture else 1.0),
                heart_rate=hr + self._n(2.0),
                hr_signal_quality=0.8 + self._n(0.06),
                audio_energy=max(0.0, (0.5 if speech else 0.15) + self._n(0.08)),
                speech_detected=speech,
                num_speakers=2 if speech else 0,
                worn=True,
                face_detected=(speaking_block == 1),  # other person in view
                face_expression="neutral" if speaking_block == 1 else None,
            ))
        return samples

    # -----------------------------------------------------
    # Scenario 4: Multi-party High-energy
    # -----------------------------------------------------
    def gen_multiparty_highenergy(self, duration_s: float = 60.0) -> List[TraceSample]:
        """
        Several people, animated exchange. Overlapping speech, high HR,
        bursts of hand/body movement, expression changes.
        """
        samples = []
        n = int(duration_s / self.dt)
        for i in range(n):
            t = i * self.dt
            speech = self.rng.random() < 0.85       # dense speech
            burst = self.rng.random() < 0.25        # frequent movement bursts
            move_amt = 0.4 if burst else 0.12
            speakers = self.rng.choice([2, 3, 3, 4]) if speech else 0

            hr_ramp = min(1.0, t / 8.0)
            hr = 72.0 + (38.0 * hr_ramp)  # rises to ~110

            expr = self.rng.choice(
                ["smiling", "surprised", "laughing", "neutral"]
            ) if self.rng.random() < 0.4 else "neutral"

            samples.append(TraceSample(
                t=round(t, 3),
                accel_x=self._n(move_amt),
                accel_y=self._n(move_amt),
                accel_z=1.0 + self._n(move_amt),
                gyro_x=self._n(15.0 if burst else 3.0),
                gyro_y=self._n(15.0 if burst else 3.0),
                gyro_z=self._n(15.0 if burst else 3.0),
                heart_rate=hr + self._n(3.0),
                hr_signal_quality=0.72 + self._n(0.08),
                audio_energy=max(0.0, (0.8 if speech else 0.2) + self._n(0.12)),
                speech_detected=speech,
                num_speakers=speakers,
                worn=True,
                face_detected=True,
                face_expression=expr,
            ))
        return samples

    # -----------------------------------------------------
    # Special traces for specific tests
    # -----------------------------------------------------
    def gen_double_tap_trace(self, duration_s: float = 10.0) -> List[TraceSample]:
        """
        Ambient-alone baseline with a deliberate double-tap at t=5.0s.
        Two sharp accel spikes within 300ms.
        """
        samples = self.gen_ambient_alone(duration_s)
        # inject two taps: at 5.0s and 5.2s (200ms apart, within 300ms window)
        tap_times = [5.0, 5.2]
        for s in samples:
            for tt in tap_times:
                if abs(s.t - tt) < self.dt / 2:
                    # sharp spike on z-axis
                    s.accel_z += 1.2
                    s.double_tap = True
        return samples

    def gen_not_worn_trace(self, duration_s: float = 360.0) -> List[TraceSample]:
        """
        Device taken off and left on a table for 6 minutes.
        PPG loses contact (quality drops to ~0), device lies flat, no motion.
        Used to test the 5-minute not-worn timeout.
        """
        samples = []
        n = int(duration_s / self.dt)
        for i in range(n):
            t = i * self.dt
            samples.append(TraceSample(
                t=round(t, 3),
                accel_x=1.0 + self._n(0.003),  # flat on table
                accel_y=self._n(0.003),
                accel_z=self._n(0.003),
                gyro_x=self._n(0.05),
                gyro_y=self._n(0.05),
                gyro_z=self._n(0.05),
                heart_rate=0.0,  # NOTE: ground truth "no reading" — daemon must flag, not trust
                hr_signal_quality=0.05 + abs(self._n(0.02)),  # very poor — no skin contact
                audio_energy=max(0.0, 0.03 + self._n(0.01)),
                speech_detected=False,
                num_speakers=0,
                worn=False,  # ground truth: NOT worn
            ))
        return samples


def export_trace(samples: List[TraceSample], name: str, out_dir: str):
    """Write a trace to JSON with a clear synthetic label."""
    os.makedirs(out_dir, exist_ok=True)
    payload = {
        "_meta": {
            "SYNTHETIC": True,
            "warning": "THIS IS SYNTHETIC DATA — NOT REAL SENSOR READINGS",
            "scenario": name,
            "sample_count": len(samples),
            "generated_by": "TraceGenerator v1",
        },
        "samples": [asdict(s) for s in samples],
    }
    path = os.path.join(out_dir, f"{name}.json")
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    return path


def load_trace(path: str) -> List[TraceSample]:
    """Load a trace back from JSON."""
    with open(path) as f:
        payload = json.load(f)
    if not payload.get("_meta", {}).get("SYNTHETIC"):
        raise ValueError(f"Trace at {path} is not labeled synthetic — refusing to load")
    return [TraceSample(**s) for s in payload["samples"]]


def generate_all(out_dir: str):
    """Generate all standard scenario traces."""
    gen = TraceGenerator()
    traces = {
        "idle_dormant": gen.gen_idle_dormant(60),
        "ambient_alone": gen.gen_ambient_alone(60),
        "active_conversation": gen.gen_active_conversation(60),
        "multiparty_highenergy": gen.gen_multiparty_highenergy(60),
        "double_tap_test": gen.gen_double_tap_trace(10),
        "not_worn_test": gen.gen_not_worn_trace(360),
    }
    paths = []
    for name, samples in traces.items():
        p = export_trace(samples, name, out_dir)
        paths.append(p)
        print(f"  Generated {name}: {len(samples)} samples -> {p}")
    return paths


if __name__ == "__main__":
    here = os.path.dirname(__file__)
    print("Generating synthetic traces...")
    generate_all(here)
    print("Done.")
