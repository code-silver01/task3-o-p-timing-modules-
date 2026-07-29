# Chronis HW-1 — Complete Codebase Walkthrough

> 3,214 lines of Python · 74 tests · 18 files
> 
> Read this to understand every piece of the repo — what it does, why it's
> built that way, what changed in the final review, and what you'd say if
> someone asks about it.

---

## PART 1: What Is This Project?

Chronis is a wearable locket (see the renders — round pendant with camera,
mics, OLED display, PPG LEDs on the back). It continuously captures your life
and decides HOW MUCH to capture based on what's happening around you.

Our job (Track HW-1) is the **brain** — the software that takes sensor
readings as input and makes decisions as output:

```
IMU data ──┐
PPG data ──┤──→ daemons ──→ state machine ──→ "capture at level L3"
Audio    ──┤                                     ↓
Camera   ──┘                               camera: 10fps
                                            audio: 16kHz full quality
```

Everything runs against FAKE sensor data. When real chips arrive, you swap
`MockIMU.i2c_read()` for `real_i2c_read(0x68, ...)`. The logic above stays
identical.

---

## PART 2: The 4 Rules (Non-Negotiable)

These are enforced in the code structurally, not by comments or promises.

### Rule 1: Encrypt Before Storage
**File:** `mock_hal/mock_storage.py`

`MockStorage.write(path, payload)` checks `isinstance(payload, EncryptedPayload)`.
If you pass `RawPayload`, raw `bytes`, a `str`, or a `dict`, it raises
`EncryptionBypassAttempt`. You physically cannot write unencrypted data.

```python
# This works:
encrypted = encryptor.encrypt(raw)
storage.write("/vault/2026-07-12/camera/001", encrypted)  # ✅

# These all CRASH (on purpose):
storage.write("/vault/...", raw_payload)   # ❌ EncryptionBypassAttempt
storage.write("/vault/...", b"raw bytes")  # ❌ EncryptionBypassAttempt
storage.write("/vault/...", {"data": 1})   # ❌ EncryptionBypassAttempt
```

### Rule 2: Append-Only
**File:** `mock_hal/mock_storage.py`

If a path already exists, `write()` raises `AppendOnlyViolation`. `delete()`
ALWAYS raises `AppendOnlyViolation`. You can only ever add new records.

### Rule 3: No Fake Zeros
**Files:** `mock_hal/sensor_types.py` + every daemon

When a sensor is unavailable, the reading comes back with:
- `status = SensorStatus.UNAVAILABLE` (or `NOT_WORN` or `FAULT`)
- `unavailable_reason = UnavailableReason.I2C_TIMEOUT` (etc.)
- All value fields = `None` (never 0)

Every daemon checks `reading.is_valid` before using values. The extended
simulation proves this by deliberately killing the IMU for 10 seconds
mid-run — zero crashes, zero fake zeros, 10 unavailable events logged.

### Rule 4: No Direct Daemon Access
**All daemon files**

Daemons never import each other's internals. They communicate only through
typed output objects: `MotionOutput`, `HeartRateOutput`, `WornOutput`. This
leaves a clean seam for a permissions layer to be added later.

---

## PART 3: File-by-File Walkthrough

### Layer 1: Mock Hardware (what pretends to be real chips)

#### `mock_hal/sensor_types.py` — 132 lines
**What:** Defines every data type the system uses.

Key types:
- `SensorStatus` enum: `OK`, `UNAVAILABLE`, `NOT_WORN`, `CALIBRATING`, `FAULT`
- `UnavailableReason` enum: `SENSOR_NOT_FOUND`, `I2C_TIMEOUT`, `DEVICE_NOT_WORN`, etc.
- `SensorReading` base class: every reading has `timestamp`, `status`, and an
  `is_valid` property that returns `True` only when `status == OK`
- `IMUReading`: accel_x/y/z (in g), gyro_x/y/z (in deg/s), plus a computed
  `accel_magnitude` property that returns `None` if unavailable
- `PPGReading`: heart_rate_bpm, spo2_percent, signal_quality (0-1)
- `AudioReading`: energy_rms (0-1), peak_db, sample_rate_hz, speech_detected,
  num_speakers
- `CameraReading`: frame_id, width, height, compression_level, face info
- `EncryptedPayload`: the ONLY type storage accepts (Rule 1)
- `RawPayload`: explicitly REJECTED by storage (Rule 1)

**Why it matters:** Rule 3 lives here. The `is_valid` property is what prevents
fake zeros from ever entering the pipeline.

#### `mock_hal/mock_hal.py` — 329 lines
**What:** Fake sensor classes simulating real chip APIs.

Each sensor class (MockIMU, MockPPG, MockCamera, MockMicrophone, MockGPIO) has:
- A `set_available(False, reason)` method to simulate failure
- A read method (`i2c_read()`, `capture_frame()`, `read_chunk()`, `gpio_read()`)
  that checks availability before returning data
- `set_values(...)` to control what the fake sensor returns
- `set_noise(level)` to add gaussian noise (realistic simulation)

The `MockHAL` class wraps all five sensors and provides a unified interface:
```python
hal = MockHAL()
hal.read_imu()        # → IMUReading
hal.read_ppg()        # → PPGReading
hal.capture_frame()   # → CameraReading
hal.read_audio()      # → AudioReading
hal.set_all_available(False)  # kill everything at once
```

**Real chip mapping:**
- MockIMU → ICM-42688-P (I2C address 0x68)
- MockPPG → MAX30102 (I2C address 0x57)
- MockCamera → IMX219 (CSI interface)

#### `mock_hal/mock_storage.py` — 107 lines
**What:** Fake filesystem enforcing Rules 1 and 2. Covered above in the rules
section.

---

### Layer 2: Synthetic Traces (the fake-but-realistic sensor data)

#### `traces/trace_generator.py` — 314 lines
**What:** Generates pre-scripted sensor data for 6 scenarios.

Each scenario produces a list of `TraceSample` objects with realistic values:

**1. `idle_dormant` (60s)** — Device on a sleeping person.
- Accel: gravity on x-axis (lying down), near-zero movement
- HR: 58 bpm, very stable, high signal quality
- Audio: near-silent (energy ~0.02)

**2. `ambient_alone` (60s)** — Worn, upright, quiet room.
- Accel: gravity on z-axis (upright), occasional small shifts (3% chance)
- HR: 68 bpm, stable
- Audio: low background (energy ~0.08), no speech

**3. `active_conversation` (60s)** — Talking with one other person.
- Accel: gesture bursts (15% chance), motion increases over time
- HR: ramps from 68 to 86 bpm over first 10 seconds
- Audio: 70% speech density, 2 speakers alternating every ~4 seconds
- Face detection of the other person

**4. `multiparty_highenergy` (60s)** — Group of people, animated exchange.
- Accel: frequent movement bursts (25% chance), higher amplitude
- HR: ramps from 72 to 110 bpm
- Audio: 85% speech density, 2-4 speakers, overlapping
- Expression changes: smiling, surprised, laughing

**5. `double_tap_test` (10s)** — Quiet baseline with two deliberate accel
spikes at t=5.0s and t=5.2s (200ms apart, within the 300ms window).

**6. `not_worn_test` (360s / 6 minutes)** — Device on a table for 6 minutes.
- Accel: flat on table, near-zero movement
- HR: 0 (no skin contact — daemon must flag, not trust)
- Signal quality: ~0.05 (near-zero)
- Worn ground truth: False

Every trace JSON has a `_meta` field:
```json
{"SYNTHETIC": true, "warning": "THIS IS SYNTHETIC DATA", "scenario": "..."}
```

The `load_trace()` function refuses to load any file without this flag.

---

### Layer 3: Daemons (the processing logic)

#### `daemons/motion_daemon.py` — 239 lines
**What:** Reads IMU data and computes everything about how the device is moving.

**Complementary Filter** (class `ComplementaryFilter`):
- Fuses accelerometer and gyroscope into stable pitch/roll
- Accelerometer: trustworthy long-term (gravity always points down) but noisy
  short-term (vibrations, hand movements)
- Gyroscope: smooth short-term (measures rotation directly) but drifts long-term
  (accumulated integration error)
- Alpha=0.98 means: each step, take 98% from gyro (smooth) and 2% from accel
  (corrects drift). Same concept as your VestGuard orientation tracking.

```
pitch = 0.98 * gyro_integrated_pitch + 0.02 * accel_derived_pitch
```

**Motion State Classification** (method `_classify_motion`):
- Computes variance of accel magnitude over a 1-second window (20 samples)
- variance < 0.004 → STILL
- variance < 0.05 → WALKING
- variance ≥ 0.05 → ACTIVE

**Posture Classification** (method `_classify_posture`):
- Computes total tilt = sqrt(pitch² + roll²) from the complementary filter
- tilt < 45° → UPRIGHT (gravity mostly on z-axis)
- tilt ≥ 45° → LYING (gravity shifted to x or y axis)

**Gesture Energy** (method `_gesture_energy`):
- Windowed RMS of (accel_magnitude - 1.0) over the last second
- Basically: how much is the device deviating from just sitting still at 1g?
- Higher = more energetic movement happening right now

**Change-Point Detection** (method `_detect_change_point`):
- Compares the mean gesture energy of the last second vs the previous second
- If the ratio exceeds 3.0, flags a "change point" — a sudden shift in
  activity pattern (e.g., person was sitting and suddenly starts gesturing)

**Double-Tap Detection** (methods `_detect_tap` + `_check_double_tap`):
- A tap = the **rising edge** of a sharp accel spike (deviation > 0.6g from 1g)
- EDGE-TRIGGERED: only the transition INTO a spike counts. A sustained 200ms
  spike is ONE tap, not one per sample.

**BUG FOUND IN REVIEW:** Originally, the tap detector was LEVEL-triggered
  (every sample above threshold counted as a separate tap). This meant:
  - A sustained accel spike (person swinging their arm) would register as
    many taps and false-fire the double-tap detector
  - Three taps in quick succession would fire TWICE (taps 1+2, then 2+3)

  Fixed with:
  - `_in_spike` boolean tracks if we're currently inside a spike
  - A tap is only registered when `above_threshold AND NOT _in_spike` (the edge)
  - After a double-tap fires, `_tap_timestamps.clear()` prevents re-firing

```python
# BEFORE (broken): any sample above threshold = a tap
deviation = abs(mag - 1.0)
return deviation > self.TAP_SPIKE_THRESHOLD

# AFTER (fixed): only the rising edge = a tap
above = abs(mag - 1.0) > self.TAP_SPIKE_THRESHOLD
is_edge = above and not self._in_spike  # only the transition
self._in_spike = above
return is_edge
```

This is the kind of bug that would be invisible in simulation but would make
the real device constantly bookmark random moments during normal arm movement.

#### `daemons/heart_rate_daemon.py` — 112 lines
**What:** Reads PPG data and scores how much you should trust the reading.

The combined quality score blends three signals:
- **Sensor's own quality** (70% weight): the MAX30102 reports its confidence.
  If the sensor says 0.2, we don't override that.
- **Beat-to-beat stability** (30% weight): how consistent is HR compared to
  the last 10 readings? A sudden jump from 70 to 140 is suspicious.
- **Physiological plausibility** (binary gate): HR outside 30-220 bpm?
  Quality = 0. Hard stop.

The combined score maps to labels:
- ≥ 0.7 → GOOD (trustworthy)
- ≥ 0.4 → FAIR
- < 0.4 → POOR
- Trust threshold: 0.6 (below this, `trustworthy = False`)

**BUG FOUND IN REVIEW:** Originally, the weighting was 50% sensor + 30%
stability + 20% constant. This meant a sensor reporting quality=0.2 could
still land at combined=0.6 and be marked trustworthy. Fixed by increasing
sensor weight to 70% and removing the constant term.

#### `daemons/anchor_gesture_detector.py` — 103 lines
**What:** Takes double-tap events and opens a 30-second annotation window.

**THE CRITICAL DISTINCTION** (sprint doc warns "this is easy to get wrong"):
- A double-tap is ONLY an annotation marker
- It does NOT change the capture level
- It does NOT trigger the camera
- It does NOT start recording

**How it's enforced structurally:**
The `AnchorGestureDetector` class has zero capture-related attributes or
methods. It can't change capture state because it has no reference to any
capture system. The negative tests verify:

```python
# These attributes must NOT exist:
forbidden = ['capture_level', 'set_level', 'trigger_camera',
             'start_recording', 'camera_burst', 'capture_intensity']
for attr in forbidden:
    assert not hasattr(detector, attr)
```

What it does:
1. `on_double_tap(timestamp)` → creates an `AnnotationWindow` (15s before
   to 15s after the tap) and emits a `MomentMarkedSignal`
2. `attach_note(timestamp, text)` → the phone sends back a text note; it
   gets linked to the nearest annotation window

#### `daemons/capture_daemons.py` — 141 lines
**What:** Camera and audio daemons that capture data and encrypt before storage.

`CameraDaemon.capture_and_store(reading, date)`:
1. Checks `reading.is_valid` (Rule 3: skip unavailable frames)
2. Serializes frame metadata to bytes
3. Wraps in `RawPayload`
4. Passes through `encryptor.encrypt(raw)` → `EncryptedPayload`
5. Calls `storage.write(path, encrypted)` (which only accepts EncryptedPayload)

`AudioDaemon` works the same, with one special case:
- Level "L0" = ring-buffer only, never written to disk. The method returns
  `True` but increments `chunks_buffered_only` instead of `chunks_stored`.

**StubEncryptionDaemon:** A placeholder for HW-2's real encryption daemon.
Same interface (`encrypt(RawPayload) → EncryptedPayload`) but uses trivial
XOR instead of real ATECC608B crypto. When HW-2's code is ready, you change
one import line.

#### `daemons/worn_detector.py` — 171 lines
**What:** Decides if the device is on a body using a 3-signal weighted vote.

**The vote:**

| Signal | Weight | Why it's weighted this way |
|--------|--------|--------------------------|
| HR signal quality | 55% | Best skin-contact indicator. PPG returns ~0 quality without skin. |
| Orientation variance | 30% | A worn device subtly shifts as the body moves. A table device is perfectly still. |
| Accel activity | 15% | Micro-vibrations of a living body. Least reliable (a vibrating table fools it). |

Score ≥ 0.5 → instantaneously worn.

**State machine:**

```
WORN ──(score < 0.5 continuously for 5 minutes)──→ NOT_WORN
                                                        │
NOT_WORN ──(score ≥ 0.5)──→ WAKING_UP                  │
                               │                        │
WAKING_UP ──(15 seconds pass)──→ self_test() ──→ WORN   │
WAKING_UP ──(score drops again)──→ NOT_WORN ◄───────────┘
```

**ADDED IN REVIEW:** `_run_self_test()` — checks that sensors are returning
plausible values before completing the wake-up (HR quality > 0.3, some
orientation variance, some accel activity). Spec says "run a quick self-test."

**ADDED IN REVIEW:** `metadata_entry()` — returns a dict for every metadata
write. Spec says "Log the worn/not-worn state on every single metadata write."

**Not-worn behavior:**
- Camera: OFF
- Audio: ring-buffer only (not saved to disk)
- Motion sensor: drops to low sampling rate
- HR sensor: drops to minimal rate

**Worn-again behavior:**
- 15-second GRADUAL wake-up (not instant jump)
- Self-test runs
- State machine **restarts at L1** (never snaps back to pre-removal level)

---

### Layer 4: The State Machine (the brain)

#### `state_machine/capture_state_machine.py` — 325 lines
**What:** The 6-level capture-intensity decision engine.

The device is always in exactly one level (L0 through L5), recalculated
every 500 milliseconds. Each level tells camera and audio what to do:

| Level | Name | Camera | Audio |
|-------|------|--------|-------|
| L0 | Dormant | OFF | 8kHz buffer only, NOT saved |
| L1 | Ambient | 0.5 fps, heavy compression | 8kHz stereo, saved |
| L2 | Passive | 1 fps, moderate compression | 16kHz continuous |
| L3 | Active | 10+ fps, low compression | 16kHz full quality |
| L4 | Engaged | Max fps, minimal compression | 16kHz dual-boosted |
| L5 | Peak | 30fps, best quality | 48kHz lossless |

**Going UP (happens immediately when condition is met):**

L0 → L1: `worn AND upright AND hr_quality > 0.5 AND NOT asleep`

L1 → L2: ANY of:
- Motion state is walking or active
- Background speech detected
- HR is 5-10% above baseline
- Time is 8am-10pm

L2 → L3: ANY of:
- Own voice active for 5+ seconds continuously
- Purposeful upper-body motion
- HR > 15% above baseline
- Clear two-person exchange detected

L3 → L4: ALL of these simultaneously (within 60-second window):
- Speech more than 40% of the time
- More than 1 distinct speaker
- HR > 20% above baseline OR voice energy notably above baseline

L4 → L5: At least 3 of these 6:
1. Voice energy far above personal average (> 1.8x baseline)
2. HR 30%+ above baseline OR HRV collapse
3. Burst of rapid movement
4. More than 2 speakers with overlapping speech
5. Facial expression change from neutral
6. Stress index above personal 90th percentile

L5 holds as long as 2 or more of those 6 stay active.

**Going DOWN (hysteresis — must hold for set time):**

| Drop | Hold time | Condition |
|------|-----------|-----------|
| L5 → L4 | 45 seconds | 1 or fewer L5 conditions active |
| L4 → L3 | 60 seconds | None of L4 conditions active |
| L3 → L2 | 90 seconds | None of L3 conditions active |
| L2 → L1 | 120 seconds | None of L2 conditions active |
| L1 → L0 | 5 minutes | Device continuously not-worn |

**Why hysteresis matters:** Without it, a 2-second pause in conversation would
drop from L4 to L2, then back up when speaking resumes — camera FPS would
thrash between 30 and 1 every few seconds. The hold timers make sure levels
only change on sustained scene changes.

**BUG FOUND IN REVIEW:** Random noise in the ambient audio trace would
occasionally spike `voice_energy` above the threshold, resetting the L4
down-timer. Since these spikes happened every ~15 seconds and the timer needs
60 seconds continuous, the system could never step down from L4.

Fixed by smoothing voice_energy over a 1-second window so single-sample noise
doesn't count as a real speech event.

**ADDED IN REVIEW:** `restart_at_L1(timestamp)` — after the worn detector
completes its 15-second wake-up, the state machine drops to L1 and re-assesses
upward. Spec explicitly requires this.

#### `state_machine/extended_run.py` — 349 lines
**What:** The full integration test. Chains scenarios and runs everything.

**Scenario chain:**
```
idle (30s) → ambient (40s) → conversation (60s) → high-energy (60s)
→ conversation (40s) → ambient (340s, long quiet tail)
```

Total: 11,400 samples, 570 seconds.

**What runs:**
- IMU readings → motion daemon → orientation, motion state, posture, gestures
- PPG readings → heart rate daemon → signal quality scoring
- Worn detector → 3-signal vote
- Signal extractor → converts daemon outputs into CaptureSignals
- State machine → ticks every 500ms, decides level
- Anchor gesture detector → handles double-taps

**Rule 3 injection:** Between t=90s and t=100s, the IMU is deliberately set to
UNAVAILABLE. The motion daemon returns `valid=False`, the state machine
continues on remaining sensors. 10 unavailable events logged, zero crashes.

**ADDED IN REVIEW:** `AsleepTracker` class — spec says L0 enters when "lying
still 20+ min, low heart-rate variability." The old code used an instantaneous
heuristic (HR < 62 and no movement). The new tracker requires the condition
to hold continuously for 20 minutes, with HRV (standard deviation of HR)
below 2.0 bpm.

**Expected output:**
```
L0 → L1  (upright + worn + HR quality ok)
L1 → L2  (time-of-day likelihood)
L2 → L3  (heart rate >15% above baseline)
L3 → L4  (speech>40% + multi-speaker + arousal)
L4 → L5  (3+ signals converge)
L5 → L4  (hysteresis 45s)
L4 → L3  (hysteresis 60s)
L3 → L2  (hysteresis 90s)
```

---

### Layer 5: Integration & Day 5 Prep

#### `integration/power_ceiling_combiner.py` — 33 lines
**What:** HW-1's side of the Day 5 power-ceiling contract.

Sprint doc says: "if the state machine says L5 but battery is Critical (caps at
L3), the lower of the two must always win."

```python
def effective_level(state_machine_level, power_ceiling):
    return min(state_machine_level, power_ceiling)
```

Pre-tested with the exact conflict case from the spec. On Day 5, wiring this
with HW-2's power daemon is a one-liner.

---

## PART 4: All Tunable Constants

These are educated guesses that WILL need recalibration on real hardware.

**Motion daemon:**
- `STILL_VAR_THRESHOLD = 0.004` — accel variance below this = still
- `WALKING_VAR_THRESHOLD = 0.05` — between still and this = walking
- `TAP_SPIKE_THRESHOLD = 0.6` — accel deviation from 1g to count as a tap
- `TAP_WINDOW_S = 0.300` — two taps within 300ms = double-tap
- `CHANGE_POINT_RATIO = 3.0` — recent energy vs baseline to flag a change

**Heart rate daemon:**
- `GOOD_THRESHOLD = 0.7`, `FAIR_THRESHOLD = 0.4`, `TRUST_THRESHOLD = 0.6`

**Worn detector:**
- `W_HR = 0.55`, `W_ORIENT = 0.30`, `W_ACCEL = 0.15` — vote weights
- `WORN_THRESHOLD = 0.5` — score above this = worn
- `NOT_WORN_TIMEOUT_S = 300` — 5 minutes
- `WAKEUP_DURATION_S = 15.0` — 15-second gradual wake-up
- `ORIENT_VAR_REF = 5.0` — orientation variance that means "clearly worn"
- `ACCEL_ACT_REF = 0.03` — accel activity that means "clearly worn"

**State machine hysteresis:**
- L5→L4: 45s, L4→L3: 60s, L3→L2: 90s, L2→L1: 120s, L1→L0: 5min not-worn

**Asleep tracker:**
- `ASLEEP_HOLD_S = 1200` — 20 minutes continuous lying still + low HRV

**Complementary filter:**
- `alpha = 0.98` — 98% gyro trust, 2% accel correction per step

---

## PART 5: Test Suite (74 Tests)

**test_mock_hal.py (30 tests):**
- Every sensor returns valid readings when available
- Every sensor returns SensorUnavailable (not zero) when down (Rule 3)
- Storage rejects raw data in 5 different forms (Rule 1)
- Storage rejects overwrites and deletes (Rule 2)
- PPG not-worn is distinct from unavailable
- IMU fault injection
- All-sensors toggle on/off

**test_motion_daemon.py (10 tests):**
- Still detection when no motion
- Active detection on high variance
- Posture: upright (gravity on z) vs lying (gravity on x)
- Rule 3: unavailable reading → explicit UNAVAILABLE state
- Double-tap fires within 300ms window
- Double-tap does NOT fire when taps are 1+ second apart
- **[NEW]** Triple-tap fires exactly once (regression for refractory bug)
- **[NEW]** Sustained spike is one tap not many (regression for edge-trigger bug)
- Change-point detection on sudden activity burst

**test_daemons.py (15 tests):**
- HR daemon: good quality on stable readings
- HR daemon: not-worn → unavailable, never fake HR
- HR daemon: low sensor quality is NOT marked trustworthy
- HR daemon: implausible HR (300 bpm) is NOT trusted
- HR daemon: sudden HR jump lowers combined quality
- Anchor: opens exactly a 30-second window
- Anchor: emits moment_marked signal
- **Anchor: structurally has NO capture-related attributes** (the key test)
- Anchor: emitted signal carries no capture commands
- Anchor: attach_note works
- Worn detector: starts worn with good signals
- Worn detector: 4 minutes bad signal → still worn (needs 5 min)
- Worn detector: 5+ minutes → transitions to not-worn
- Worn detector: not-worn → worn again goes through 15s gradual wake-up
- Worn detector: HR quality dominates the vote (55% weight)

**test_state_machine.py (19 tests):**
- Starts at L0
- L0 exit needs worn + upright
- L1→L2 on motion, L1→L2 on time-of-day
- L2→L3 on high HR
- L4 requires ALL three conditions (speech + speakers + arousal)
- L4 NOT reached with only partial conditions
- L5 requires 3 of 6 signals
- Level config matches current level
- L5 holds before 45s hysteresis expires
- L5 steps down after 45s
- No flicker: condition reappearing resets the down-timer
- **[NEW]** restart_at_L1 after wake-up drops level and logs cause
- Camera daemon encrypts before storing (Rule 1)
- Camera daemon skips unavailable frames (Rule 3)
- Audio L0 = buffer-only, never stored
- Audio L2 is stored encrypted
- Storage rejects raw data from any daemon

---

## PART 6: Bugs Found and Fixed During Review

### Bug 1: Double-tap false-fired on sustained movement (CRITICAL)
**Problem:** A continuous accel spike (person swinging arm) registered as
multiple taps. A 200ms spike at 20Hz = 4 samples = 4 "taps" = 2 double-tap
events. On real hardware, energetic gesturing would constantly bookmark
random moments.

**Root cause:** Level-triggered detection. Every sample above threshold
counted as a separate tap.

**Fix:** Edge-triggered detection. Only the TRANSITION into a spike counts.
Plus: refractory clear after firing prevents triple-tap double-counting.

### Bug 2: HR quality scoring let bad readings through
**Problem:** Sensor quality = 0.2, but combined score = 0.6 (exactly at trust
threshold) because stability and plausibility inflated it.

**Root cause:** Sensor quality weight was only 50%; a constant 20% term
padded the score up.

**Fix:** Sensor quality weight increased to 70%, constant term removed.

### Bug 3: Hysteresis down-timer kept resetting on noise (IMPORTANT)
**Problem:** Random audio noise spikes in the ambient trace would briefly push
voice_energy above baseline×1.3, making L4_count=1 for one sample. This reset
the 60-second down-timer. Since spikes came every ~15s, the timer could never
complete.

**Root cause:** Raw per-sample voice energy used for level conditions.

**Fix:** 1-second smoothing window on voice energy. Single-sample noise
doesn't count as a real speech event.

### Bug 4: State machine didn't restart at L1 after wake-up (SPEC VIOLATION)
**Problem:** Spec explicitly says "restart at L1 and re-assess upward." No
code existed to do this.

**Fix:** Added `restart_at_L1()` method + wired into the run loop at the
moment the worn detector transitions from WAKING_UP to WORN.

### Bug 5: Asleep detection was instantaneous, not 20 minutes (SPEC VIOLATION)
**Problem:** Spec says "lying still 20+ min, low heart-rate variability." Code
used an instantaneous check (HR < 62 and no movement in current sample).

**Fix:** Added `AsleepTracker` class that requires the lying+still+low-HRV
condition to hold continuously for 20 minutes.

---

## PART 7: How This Connects to VestGuard

For context if anyone asks about your prior work:

| VestGuard | Chronis HW-1 |
|-----------|-------------|
| Dual IMU (MPU6050 + ADXL345) | Single IMU (ICM-42688-P, better specs) |
| 5-state posture FSM | 6-level capture intensity SM |
| Hard-fall + soft-fall detection | Double-tap + change-point detection |
| Signal quality on accel data | Signal quality on PPG data |
| ESP32-S3 firmware | Radxa Zero 3W (Linux-based) |
| Real-time Serial/Socket.IO | Mock HAL → future real HAL swap |
| Threshold-based classification | Same approach, more input signals |

The complementary filter concept is identical across both projects.

---

## PART 8: What's Left (Day 5 + What Needs Real Hardware)

**Day 5 integration (needs other tracks):**
- Wire worn detector ↔ HW-2 power daemon
- Wire state machine ↔ power ceiling (our combiner is pre-built)
- Wire anchor gesture → HW-3 BLE alerts
- Full-stack run with all three tracks' code live

**Needs real hardware (documented in KNOWN_GAPS.md):**
- All threshold constants need recalibration
- Real I2C timing and bus conflicts
- Real audio DSP for speech/speaker detection
- Physical worn/not-worn testing on actual bodies
- Battery behavior under real load
- Complementary filter alpha tuning for real gyro drift
