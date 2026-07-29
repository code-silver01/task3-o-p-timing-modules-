# HARDWARE READINESS REPORT

**Chronis Hardware Sprint — Simulation-First Firmware Build**
**Status: Day 4 Gate MET · 242 tests passing · full pipeline working**

---

## Verdict

The codebase is ready to receive real hardware with **driver-swaps only**.
All firmware logic above the driver layer is built, tested, and running
together against the mock hardware layer. Hardware arrival triggers an
integration sprint, not a build sprint.

## Test summary

| Track | Tests | Coverage |
|-------|-------|----------|
| HW-1 Sensor & Motion | 74 | Mock HAL, traces, all daemons, worn detector, 6-level state machine, extended run |
| HW-2 Security & Boot | 119 | Encryption daemon (AES-256-GCM + X25519 + Ed25519), key hierarchy, boot matrix (all 9 failure rows), watchdog, power daemon (all 4 states), battery health |
| HW-3 Connectivity & Cloud | 39 | Storage manager, double-confirmation deletion, OTA (sig + rollback), BLE daemon (8 services, Numeric Comparison pairing), orchestration, cloud gateway, canonical DB |
| Day 5 Integration | 10 | All four cross-track connections |
| **Total** | **242** | |

## Day 4 Gate conditions

- **Zero crashes** across the 570-second extended simulated session — including
  a deliberate 10-second IMU failure injection mid-run
- **Zero Rule 1 violations** — storage accepts only encrypted records
  (type-enforced in HW-1 mock storage, HW-3 storage manager, and factory-token
  gated in HW-2's EncryptedRecord)
- **Zero Rule 2 violations** — append-only enforced in mock storage, the HW-3
  storage manager, and at the SQLite level in the canonical record DB
  (BEFORE UPDATE / BEFORE DELETE triggers)
- **Zero Rule 3 violations** — every mock sensor returns explicit
  unavailable-with-reason; the injection run logged 10 unavailable events and
  produced zero fake zeros
- **Zero Rule 4 violations** — every cross-daemon and cross-track connection
  goes through a typed interface (DeviceStateProvider, verify/decrypt
  callables, phone_notifier callback, effective_level combiner)

## The four Day 5 cross-track connections — tested

1. **Worn detector (HW-1) → Power accounting (HW-2):** not-worn accumulates
   zero camera/audio active-seconds. Proven in `test_day5_integration.py`.
2. **Power daemon (HW-2) → Capture ceiling (HW-1):** the exact conflict case
   from the spec — state machine wants L5, battery Critical caps at L3 —
   resolves to L3. Lower always wins, tested for all four power states.
3. **Anchor gesture (HW-1) → BLE Alerts + Annotation (HW-3):** a double-tap
   fires `double_tap_moment_marked` over the real BLE daemon; a phone note
   returns via the Annotation service and lands on the tap's timestamp.
   The annotation-only guarantee holds under integration (capture level
   unchanged by taps).
4. **BLE Device Info accuracy (HW-3):** reports the live capture level and
   battery values, verified to change when the underlying state changes —
   not placeholders.

## End-to-end pipeline (working)

```
fake sensor data → capture-intensity decision → encrypted upload
→ vault storage (Rule 1+2) → gateway verify → decrypt → structured event
→ canonical record DB (append-only at DB level)
→ device-side records deleted only after double confirmation
```

Run it: `cd hw-track-3-connectivity && python3 e2e_pipeline.py`

## What still needs real hardware (honest gaps, per Section 7)

- All sensor thresholds (tap detection, motion variance, worn-vote weights,
  complementary-filter alpha) are calibrated against synthetic traces only
- Real I2C bus timing, address conflicts, and signal integrity
- Power/thermal numbers are datasheet projections, not measurements
- Enclosure CAD is datasheet-dimension only — no physical fit check
- Real audio DSP (speech detection, speaker counting) does not exist yet;
  traces provide these as fields
- Physical worn/not-worn behavior on actual bodies
- The e2e pipeline currently runs with the stub cipher for the transport hop;
  swapping in HW-2's real daemon end-to-end is the first integration-day task

## Component spec list (locked, for procurement)

| Component | Part | Role |
|-----------|------|------|
| IMU | ICM-42688-P | 6-axis motion |
| PPG | MAX30102 | Heart-rate / SpO2 |
| Crypto | ATECC608B | Secure key storage |
| Camera | IMX219 | Video capture |
| RTC | DS3231-class | Clock backup |
| Compute | Radxa Zero 3W | Main board |
