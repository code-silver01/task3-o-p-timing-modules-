# Chronis HW-1 — Sensor &amp; Motion Logic

The "brain" of the Chronis wearable: decides moment-to-moment how much the
device should capture, based on motion, heart rate, and gestures. Fully
simulation-based — no physical chip required.

## What's in here

```
hw-track-1-sensors/
├── mock_hal/                  # Mock hardware layer + storage
│   ├── sensor_types.py        #   All reading types + Rule 1/3 enforcement types
│   ├── mock_hal.py            #   MockIMU, MockPPG, MockCamera, MockMic, MockGPIO
│   └── mock_storage.py        #   Rule 1 (encrypt-before-write) + Rule 2 (append-only)
├── traces/
│   └── trace_generator.py     # 4 scenario traces + double-tap + not-worn traces
├── daemons/
│   ├── motion_daemon.py       # Orientation, motion state, posture, gesture,
│   │                          #   change-point, double-tap
│   ├── heart_rate_daemon.py   # Signal quality scoring
│   ├── anchor_gesture_detector.py  # Double-tap = annotation ONLY (never capture)
│   ├── capture_daemons.py     # Camera + audio daemons (Rule 1 handoff)
│   └── worn_detector.py       # 3-signal weighted vote, 5-min timeout, 15s wake-up
├── state_machine/
│   ├── capture_state_machine.py  # 6-level L0-L5 + exact transitions + hysteresis
│   └── extended_run.py        # Full chained-scenario simulation
└── tests/                     # 74 tests
```

## Quick start

```bash
pip install -r ../requirements.txt   # numpy, pytest

# run everything
bash run_all.sh

# or individually:
python -m pytest tests/ -v                 # all 74 tests
python traces/trace_generator.py           # generate scenario traces
python state_machine/extended_run.py       # full simulation with transition log
```

## How to test each piece

**Test the mock HAL and rule enforcement:**
```bash
python -m pytest tests/test_mock_hal.py -v
```
Verifies every sensor returns `SensorUnavailable` (never fake zero), and that
storage rejects raw/unencrypted data and overwrites.

**Test the motion daemon:**
```bash
python -m pytest tests/test_motion_daemon.py -v
```
Covers posture (upright vs lying), motion state, double-tap within 300ms,
change-point detection, and Rule 3 handling of bad readings.

**Test the daemons (HR, anchor gesture, worn detector):**
```bash
python -m pytest tests/test_daemons.py -v
```
Key tests: the anchor detector is *structurally* proven to have no capture
control (the double-tap = annotation-only distinction), and the worn detector's
5-minute timeout + 15-second gradual wake-up.

**Test the state machine:**
```bash
python -m pytest tests/test_state_machine.py -v
```
Every L0→L5 transition rule, the L4 "all three conditions" gate, the L5
"3-of-6" gate, and hysteresis (no flicker: a condition reappearing resets the
down-timer).

**See the whole system run:**
```bash
python state_machine/extended_run.py
```
Chains idle → ambient → conversation → high-energy → cool-down. Prints every
level transition with its exact cause. Writes `extended_run_log.json` — this is
a real artifact usable as stand-in session data for calibration.

## The 4 rules, and where they're enforced

| Rule | Where | How |
|------|-------|-----|
| 1. Encrypt before storage | `mock_storage.py`, `capture_daemons.py` | `write()` only accepts `EncryptedPayload`; raw data raises `EncryptionBypassAttempt` |
| 2. Append-only | `mock_storage.py` | Overwrites and deletes raise `AppendOnlyViolation` |
| 3. No fake zeros | every daemon | Unavailable sensor → explicit status + `None` values, never 0 |
| 4. No daemon reaches into another | all modules | Daemons communicate only via typed outputs (`MotionOutput`, `HeartRateOutput`, etc.), never by touching each other's internals |

## Expected extended-run output

```
L0 -> L1  (upright + worn + HR quality ok)
L1 -> L2  (time-of-day likelihood)
L2 -> L3  (heart rate >15% above baseline)
L3 -> L4  (speech>40% + multi-speaker + arousal)
L4 -> L5  (3+ signals converge)
L5 -> L4  (hysteresis 45s)
L4 -> L3  (hysteresis 60s)
L3 -> L2  (hysteresis 90s)
```

Clean ascent as the scene intensifies, hysteresis-gated descent as it quiets —
no flickering.
