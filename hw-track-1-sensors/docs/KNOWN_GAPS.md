# HW-1 Known Gaps — What Simulation Does NOT Prove

Per Section 7 of the sprint doc: overclaiming would be more dangerous than the
gaps themselves. This is the honest list for Track HW-1.

## Cannot be validated without real hardware

- **Real I2C timing and bus behavior** — the mock HAL returns instantly; the real
  ICM-42688-P and MAX30102 share a bus and have read latencies, clock stretching,
  and potential address conflicts that only appear on silicon.
- **Real accelerometer noise profile** — our tap threshold (0.6g deviation) and
  motion-variance thresholds are educated guesses. They WILL need recalibration
  against a real IMU on a real body.
- **Whether the worn-detector weights are right** — 55/30/15 weighting is a design
  choice validated only against synthetic traces. Real PPG skin-contact behavior,
  real clothing interference, and real false-positive scenarios (device in a
  moving bag) need on-body testing.
- **Complementary filter alpha (0.98)** — tuned for our synthetic noise levels;
  real gyro drift rates differ per unit.
- **Audio pipeline realism** — speech detection, speaker counting, and voice-energy
  baselines are provided as trace fields here. On real hardware these come from an
  actual audio DSP chain that doesn't exist yet.

## Simplifications made (documented, deliberate)

- **Encryption is a stub** — `StubEncryptionDaemon` (XOR + SHA-256) holds the seam
  for HW-2's real ATECC608B-backed daemon. The *interface* and Rule 1 enforcement
  are real; the cryptography is not.
- **Stress index is a proxy** — computed from audio energy + HR delta. The real
  stress model is not defined yet in any track.
- **Own-voice detection is approximate** — the trace marks speech + speaker count;
  distinguishing the wearer's voice from others requires the real mic array.
- **Hour-of-day is fixed at 12** in the extended run; time-of-day transitions are
  unit-tested separately.

## What IS proven in simulation

- All four sprint rules enforced structurally (typed storage, append-only,
  explicit unavailability, interface-only daemon communication)
- Every L0–L5 transition rule and every hysteresis timer, exactly per spec
- Double-tap = annotation-only, proven with structural negative tests
- Worn detector 5-minute timeout, 15-second gradual wake-up, self-test,
  restart-at-L1 — the full lifecycle
- Zero crashes / zero fake zeros under deliberate mid-run sensor failure
