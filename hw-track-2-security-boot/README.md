# HW-Track-2 — Security and Boot Logic
## Chronis — Hardware Task 1, 4-Day Simulation-First Firmware Sprint

**Project:** Chronis wearable device firmware
**Track:** HW-2 — Security and Boot Logic (1 of 3 parallel tracks)
**Sprint duration:** 4 days, simulation-only
**Hardware status:** No physical devices exist. All code runs against a mock hardware layer. Boards are purchased only after this sprint is validated.
**Stack:** Python 3.12, `cryptography` library for real crypto primitives, `pytest` for all test suites
**Final test count:** 119 tests, all passing, zero warnings

---

## Table of Contents

1. [Mission and Context](#1-mission-and-context)
2. [Non-Negotiable Rules](#2-non-negotiable-rules)
3. [Repository Layout](#3-repository-layout)
4. [Quick Start](#4-quick-start)
5. [Day 1 — Mock Crypto Interface and Encryption Daemon](#5-day-1--mock-crypto-interface-and-encryption-daemon)
6. [Day 2 — Boot Sequence and Failure Handling](#6-day-2--boot-sequence-and-failure-handling)
7. [Day 3 — Watchdog, Power Management, Battery Health, Enclosure](#7-day-3--watchdog-power-management-battery-health-enclosure)
8. [Day 4 — Consolidated Report](#8-day-4--consolidated-report)
9. [Test Results Summary](#9-test-results-summary)
10. [Interfaces Exposed to Other Tracks](#10-interfaces-exposed-to-other-tracks)
11. [Component Spec List](#11-component-spec-list)
12. [Hardware Gap List](#12-hardware-gap-list)

---

## 1. Mission and Context

Rule 1 of this sprint — "no daemon may write to disk without going through the encryption daemon first" — is the one guarantee in the entire Chronis system that cannot be bolted on later. It has to be structurally true from the first line of code.

This track's job is to make the shape of the security and boot system correct now, so that when real hardware (ATECC608B security chip, Radxa Zero 3W board) arrives, plugging it in is a driver swap, not a rewrite.

Everything in this repository is built and tested against mocks. What requires a real chip is only the driver (a few lines calling something like `i2c_read(0x68, ...)`). Everything above that layer — key derivation, encryption logic, boot failure handling, power-state logic — is pure software and fully testable without hardware.

This track runs in parallel with:
- **HW-1 (Sensors)** — camera and audio daemons hand off raw data to `EncryptionDaemon.encrypt()` before any disk write. Day 1 of this track is their blocker.
- **HW-3 (Connectivity)** — storage manager populates the encrypted vault directory via `write_record()`. The cloud gateway verifies signatures produced by this track's DIK.

---

## 2. Non-Negotiable Rules

Every line of code in this repository satisfies all four rules. The test suites prove compliance, not merely claim it.

**Rule 1 — Encryption before storage, structurally enforced.**
The only function that writes to storage (`write_record()`) requires an already-encrypted `EncryptedRecord` as input. `EncryptedRecord` itself can only be constructed by `EncryptionDaemon.encrypt()` — a module-private factory token gates the constructor, so direct construction raises `RuntimeError` before any data is stored. There is no way to hand raw bytes to storage without going through the encryption daemon.

**Rule 2 — Canonical records are append-only.**
`write_record()` checks for an existing file at the target path before writing. If the file exists, it raises `StorageError` immediately. No record can be overwritten.

**Rule 3 — No fake zeros.**
Every mock driver supports an explicit `UNAVAILABLE` state, distinct from a successful zero reading. The mock crypto chip raises `CryptoChipError` when unavailable rather than silently returning a default. The boot sequence treats `UNAVAILABLE` the same as `FAIL`. The power daemon logs an explicit message when the ADC read returns `None` rather than substituting a default battery percentage.

**Rule 4 — No daemon reaches directly into another daemon's internals.**
Each daemon (`EncryptionDaemon`, `BootSequenceManager`, `WatchdogDaemon`, `PowerManagementDaemon`) exposes a clean public interface. No daemon imports internal state from another. Cross-track consumers (HW-1, HW-3) import only the published interfaces listed in Section 10.

---

## 3. Repository Layout

```
hw-track-2-security-boot/
├── mock_crypto/
│   └── crypto_chip.py              Day 1 — mock ATECC608B API surface
├── encryption/
│   ├── keys.py                     Day 1 — DIK / DSK / UPK / ServerTransportKey
│   └── daemon.py                   Day 1 — EncryptionDaemon, EncryptedRecord
├── storage/
│   └── storage_writer.py           Day 1 — Rule 1 and Rule 2 enforcement boundary
├── boot/
│   ├── boot_sequence.py            Day 2 — boot order manager
│   └── failure_handling.py         Day 2 — per-component failure behavior table
├── watchdog/
│   └── watchdog_daemon.py          Day 3 — daemon liveness monitoring
├── power/
│   ├── power_management_daemon.py  Day 3 — real-time battery-state logic, 4 power states
│   ├── power_thermal_estimate.py   Day 3 — datasheet-based projection (planning estimate)
│   └── battery_health.py           Day 3 — charge-cycle / Coulomb counting
├── enclosure/
│   └── enclosure_spec.md           Day 3 — first-pass CAD dimensions and notes
├── tests/
│   ├── test_encryption_daemon.py   29 tests
│   ├── test_boot_sequence.py       31 tests
│   ├── test_watchdog.py            14 tests
│   └── test_power_management.py    45 tests
├── docs/
│   └── security-boot-report.md    Day 4 — consolidated report and gap list
├── requirements.txt
└── README.md
```

---

## 4. Quick Start

```bash
# From the hw-track-2-security-boot directory
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run all tests
pytest tests/ -v

# Run one suite at a time
pytest tests/test_encryption_daemon.py -v
pytest tests/test_boot_sequence.py -v
pytest tests/test_watchdog.py -v
pytest tests/test_power_management.py -v
```

Requirements:

```
cryptography>=41.0.0
pytest>=7.0.0
```

---

## 5. Day 1 — Mock Crypto Interface and Encryption Daemon

### 5.1 Mock Crypto Chip (`mock_crypto/crypto_chip.py`)

Matches the API surface the real ATECC608B driver will expose. Uses real cryptographic primitives from the `cryptography` library underneath — Ed25519 for signing and identity, X25519 for key agreement. The mock is about the hardware interface abstraction, not about weakening cryptographic correctness.

When hardware arrives, this file is replaced with a real I2C driver. Nothing above this layer changes.

Explicit failure states (Rule 3):

- `MockCryptoChip(available=False)` puts the chip in `ChipState.UNAVAILABLE`
- All methods raise `CryptoChipError` when unavailable — no silent zero substitution
- `chip.set_state(available: bool)` toggles state at runtime for injection testing

### 5.2 Key Hierarchy (`encryption/keys.py`)

Four keys, each with a distinct lifecycle:

| Key | Type | Generation | Storage | Lifecycle |
|---|---|---|---|---|
| DIK (Device Identity Key) | Ed25519 | Once, on first boot | Never leaves secure storage | Raw private key bytes are never returned by any public method. Used to sign the encrypted envelope and to seed DSK derivation. |
| DSK (Data Session Key) | AES-256 (32 bytes) | Derived daily from DIK + date via HKDF | Never stored | Recomputed on demand. Deterministic within a calendar day. Different every midnight. |
| UPK (User Public Key) | X25519 public key | Provisioned at device pairing | Stored in plaintext | Public key only — safe to store. Used for ECIES outer wrap so the user can decrypt their own data. |
| ServerTransportKey | X25519 ephemeral | Generated fresh per upload session | Never persisted | For transport to cloud gateway (HW-3 Day 4). Generation logic built now; wired when HW-3's gateway exists. |

DIK private key protection: the raw private key bytes are stored only in `_private_key` (underscore-prefixed, private by convention). No public method or property returns an `Ed25519PrivateKey` instance or raw key bytes. The test suite inspects all public attributes via `dir()` to verify this.

DSK derivation uses HKDF-SHA256 with the DIK private bytes as input key material and the ISO date string (`YYYY-MM-DD`) as the salt. This makes the DSK deterministic within a day and guaranteed different across days.

### 5.3 Encryption Daemon (`encryption/daemon.py`)

`EncryptionDaemon.encrypt(plaintext: bytes) -> EncryptedRecord` is the only function in the codebase capable of producing an `EncryptedRecord`.

**Factory token enforcement:**

```python
_FACTORY_TOKEN = object()   # module-private sentinel

class EncryptedRecord:
    def __init__(self, _token, *, ...):
        if _token is not _FACTORY_TOKEN:
            raise RuntimeError("Rule 1 structural enforcement.")
        ...
```

`_FACTORY_TOKEN` is a module-level object. Only `encrypt()` has a reference to it. Any code outside this module that tries to construct an `EncryptedRecord` directly — with any other argument — hits the `RuntimeError` before any field is assigned.

**Encryption scheme (two layers):**

1. Layer 1 — AES-256-GCM with the daily DSK
   - Random 12-byte nonce per record
   - Produces: `inner_nonce + inner_ciphertext`

2. Layer 2 — ECIES wrap with UPK
   - Generate ephemeral X25519 key pair
   - ECDH with UPK public key → shared secret
   - HKDF-SHA256 on shared secret → 32-byte wrap key
   - AES-256-GCM encrypt the layer-1 payload with the wrap key
   - Produces: `ephemeral_pub_bytes + outer_nonce + outer_ciphertext`

3. DIK signature
   - Ed25519 sign `(ephemeral_pub_bytes + outer_nonce + outer_ciphertext)` with DIK
   - Tamper-evidence: any modification to the ciphertext invalidates the signature before decryption is attempted

`EncryptedRecord.to_bytes()` serializes to a length-prefixed binary format with a `CHRONIS_ENC_V1` magic header, ready for HW-3's storage manager to write as-is. `EncryptedRecord.from_bytes()` deserializes for HW-3 reads and for tamper-testing.

### 5.4 Storage Boundary (`storage/storage_writer.py`)

```python
def write_record(record: EncryptedRecord, path: str) -> None:
```

Two checks, both mandatory:

1. `isinstance(record, EncryptedRecord)` — rejects raw bytes, strings, dicts, and any duck-typed lookalike with a `TypeError`.
2. `os.path.exists(path)` — rejects any write to an existing path with a `StorageError` (Rule 2).

Parent directories are created automatically if they do not exist.

### 5.5 Day 1 Test Results (`tests/test_encryption_daemon.py`)

**29 tests — all passing**

| Test | Result |
|---|---|
| Raw bytes rejected by write_record() | PASS |
| String rejected by write_record() | PASS |
| Dict rejected by write_record() | PASS |
| None rejected by write_record() | PASS |
| Duck-typed lookalike rejected | PASS |
| EncryptedRecord direct construction fails (wrong token) | PASS |
| EncryptedRecord direct construction fails (None token) | PASS |
| write_record() refuses to overwrite existing file | PASS |
| Encrypt/decrypt roundtrip — normal payload | PASS |
| Encrypt/decrypt roundtrip — empty bytes | PASS |
| Encrypt/decrypt roundtrip — 64 KB payload | PASS |
| Tampered ciphertext rejected at signature verification | PASS |
| Tampered signature rejected | PASS |
| Wrong UPK private key cannot decrypt | PASS |
| DSK is deterministic for the same date | PASS |
| DSK differs across calendar dates | PASS |
| DSK length is 32 bytes | PASS |
| DSK differs at midnight boundary | PASS |
| No public attribute on DIK is an Ed25519PrivateKey | PASS |
| DIK has no attribute named private_key / private_bytes | PASS |
| DIK.public_key returns Ed25519PublicKey, not private | PASS |
| DIK.sign() returns bytes, not a key | PASS |
| to_bytes() / from_bytes() roundtrip | PASS |
| from_bytes() rejects invalid magic header | PASS |
| write_record() creates file on disk | PASS |
| Written file content deserializes and decrypts correctly | PASS |
| Unavailable chip raises CryptoChipError, not a zero | PASS |
| Chip state toggle works correctly | PASS |
| ServerTransportKey generates a fresh key each time | PASS |

---

## 6. Day 2 — Boot Sequence and Failure Handling

### 6.1 Boot Order (`boot/boot_sequence.py`)

The boot sequence runs components in this exact order. Do not reorder.

```
power_rails
security_chip
clock_sync
storage
motion_sensor
heart_rate_sensor
camera
display
status_led
bluetooth
wifi
```

`BootSequenceManager` takes a `hal` dictionary mapping component names to callables that return `ComponentStatus.OK`, `ComponentStatus.FAIL`, or `ComponentStatus.UNAVAILABLE`. Components not in the map default to OK. The manager iterates the canonical `BOOT_ORDER` list and dispatches failures to `failure_handling.py`.

### 6.2 Failure Handling (`boot/failure_handling.py`)

Each row of the spec table is implemented as a separate handler function. HALT handlers and continue handlers share no code path.

| Component | Behavior | Phone Notification | Log |
|---|---|---|---|
| security_chip | SYSTEM HALT. Boot stops immediately. | Yes | Yes |
| storage | SYSTEM HALT. Boot stops immediately. | Yes | Yes |
| motion_sensor | Degraded boot. Boot continues. Audio-only inputs. | Yes | Yes |
| heart_rate_sensor | Degraded boot. Boot continues. HR features disabled. | Yes | Yes |
| camera | Audio-only boot. Boot continues. | Yes | Yes |
| display | Continue normally. Status LED becomes primary indicator. | No | Yes |
| status_led | Continue normally. | No | Yes (only) |
| bluetooth | Continue normally. Fall back to WiFi. Display icon shown. | No | Yes |
| wifi | Continue normally. Store data locally. | No | Yes |

A HALT causes `BootSequenceManager.run()` to return immediately. Components registered after the halting component are never checked. `DeviceState.HALTED` is distinct from `DeviceState.DEGRADED` and `DeviceState.READY` — they cannot be confused.

### 6.3 Day 2 Test Results (`tests/test_boot_sequence.py`)

**31 tests — all passing**

Includes: happy path (all OK reaches READY), boot order verification, one test per failure row (9 rows), HALT-stops-boot tests for security_chip and storage, degraded-continues tests for motion/HR/camera, HALT vs. degraded asymmetry assertion, multiple-degraded-failures test, and UNAVAILABLE-as-FAIL test.

---

## 7. Day 3 — Watchdog, Power Management, Battery Health, Enclosure

### 7.1 Watchdog Daemon (`watchdog/watchdog_daemon.py`)

`WatchdogDaemon` accepts a `halt_fn`, `restart_fn`, and `log_fn` at construction. Daemons are registered with `register(name, liveness_check)` where `liveness_check` returns `DaemonStatus.ALIVE`, `DaemonStatus.DEAD`, or `DaemonStatus.UNAVAILABLE`.

`check_all()` runs one liveness sweep:
- If `encryption_daemon` is not alive: calls `halt_fn`, logs, returns a `HALT` event immediately. The sweep stops. No further daemons are checked.
- If any other daemon is not alive: calls `restart_fn(name)`, logs, appends a `RESTART` event. The sweep continues.

This asymmetry is hard-coded. The encryption daemon is not treated like other daemons because Rule 1 makes every other daemon dependent on it.

### 7.2 Power Management Daemon (`power/power_management_daemon.py`)

Answers: does the device correctly change its own behavior in real time as the battery drains? This is separate from the thermal projection in `power_thermal_estimate.py`.

**Voltage-to-percent lookup:** Generic lithium discharge curve (3.0 V = 0%, 4.2 V = 100%) with linear interpolation between table points.

**Four power states:**

| State | Battery range | Camera | LED brightness | Audio | Sync | WiFi | BLE |
|---|---|---|---|---|---|---|---|
| Full Active | above 40% | up to L5 | 100% | up to L5 | enabled | on | normal |
| Conservation | 20% to 40% (inclusive) | capped at L4 | 50% | capped at L4 | throttled | on | normal |
| Critical | below 20%, at or above 5% | capped at L3 | 20% | capped at L3 | disabled | on | normal |
| Emergency | below 5% | off | pulse only | ring-buffer only | disabled | off | beacon only |

Note on boundaries: "below 20%" means strictly less than 20%, so 20% exactly is Conservation. "Below 5%" means strictly less than 5%, so 5% exactly is Critical.

States are enforced as restrictions layered on top of whatever HW-1's capture-intensity state machine would otherwise allow. The daemon caps; it does not replace the state machine.

**Charging:** When `charging_detected_fn()` returns `True`, the daemon enters `PowerState.CHARGING` regardless of voltage. A charging-animation log entry fires on entry.

**Notifications:**
- Conservation: phone notified once per entry (not on every tick)
- Critical: phone alerted immediately on entry
- Emergency: phone notified urgently on entry

**Daily power report:** `generate_daily_report()` produces a `DailyPowerReport` with a `to_json()` method. Schema includes: date, active seconds per subsystem (camera, audio, motion, heart-rate, BLE, WiFi), partial charge cycles, estimated power consumed (mWh), and time spent at each power state.

### 7.3 Battery Health (`power/battery_health.py`)

`BatteryHealthTracker.record_discharge(percent_discharged)` accumulates discharge events. One full charge cycle = 100% of capacity discharged (may span many partial events). `report()` returns a `BatteryHealthReport` with `replacement_needed = True` when cycle count reaches 500 or above — not before.

### 7.4 Power and Thermal Estimate (`power/power_thermal_estimate.py`)

**UNVERIFIED PLANNING ESTIMATE — datasheet-derived only. Do not treat as measured specs.**

Current draw per component at each capture level (L0 = idle, L5 = maximum):

| Component | L0 (mA) | L3 (mA) | L5 (mA) | Source |
|---|---|---|---|---|
| ICM-42688-P | 0.017 | 0.77 | 0.77 | TDK DS Rev1.0 |
| MAX30102 | 0.0007 | 1.8 | 10.0 | Maxim DS Rev3 |
| IMX219 | 0.0 | 150.0 | 250.0 | Sony IMX219 brief |
| ATECC608B | 0.001 | 1.5 | 2.0 | Microchip DS |
| RK3566 (Radxa Zero 3W) | 200.0 | 800.0 | 1200.0 | Radxa HW Design v1.2 |
| AP6256 BT/WiFi | 0.5 | 100.0 | 200.0 | AP6256 DS |
| DS3231 RTC | 0.17 | 0.17 | 0.17 | Maxim DS |

Estimated totals (assuming 3000 mAh battery, 3.7 V nominal):

| Level | Total current (mA) | Total power (mW) | Est. runtime (h) | Thermal warning |
|---|---|---|---|---|
| L0 | ~201 | ~743 | ~14.9 | No |
| L1 | ~412 | ~1524 | ~7.3 | No |
| L2 | ~752 | ~2782 | ~4.0 | No |
| L3 | ~1054 | ~3901 | ~2.8 | YES (above 3 W) |
| L4 | ~1354 | ~5010 | ~2.2 | YES |
| L5 | ~1663 | ~6153 | ~1.8 | YES |

Levels L3 and above exceed the 3 W thermal ceiling. Active cooling or heat-dissipating enclosure material is likely required for sustained L3+ operation.

### 7.5 Enclosure (`enclosure/enclosure_spec.md`)

First-pass enclosure envelope derived from public datasheets: **90 mm x 68 mm x 18 mm**.

Key notes:
- Radxa Zero 3W board: 65 x 37 mm
- Battery (estimated 3000 mAh LiPo): 60 x 40 mm
- Camera (IMX219 module): 25 x 24 mm, ~6 mm depth with lens
- Estimated total weight: ~85 g (unvalidated)
- Thermal flag: sustained L3-L5 operation in sealed plastic will likely require a thermally conductive shell or thermal pad on the SoC

Full dimensions, layout diagram, and gap list are in `enclosure/enclosure_spec.md`.

### 7.6 Day 3 Test Results

**Watchdog (`tests/test_watchdog.py`) — 14 tests, all passing**

| Test | Result |
|---|---|
| Encryption daemon dead triggers HALT | PASS |
| Encryption daemon dead calls halt_fn | PASS |
| Encryption daemon dead sets system_halted flag | PASS |
| Encryption daemon dead does not trigger restart | PASS |
| Encryption daemon UNAVAILABLE also triggers HALT | PASS |
| Encryption daemon failure stops the sweep | PASS |
| Other daemon dead triggers restart | PASS |
| Other daemon dead calls restart_fn with correct name | PASS |
| Other daemon dead does not trigger HALT | PASS |
| Other daemon failure leaves system_halted False | PASS |
| Other daemon failure does not stop remaining sweep | PASS |
| Multiple non-encryption failures all restarted independently | PASS |
| All daemons alive produces no events | PASS |
| Mixed alive and dead daemons handled correctly | PASS |

**Power management (`tests/test_power_management.py`) — 45 tests, all passing**

Covers: voltage lookup table, all four state boundary values, all restriction sets per state, notification behavior, charging detection, battery health cycle counting, daily report JSON schema, and thermal estimate sanity checks.

---

## 8. Day 4 — Consolidated Report

`docs/security-boot-report.md` contains:
- Day 1 through Day 3 test results with per-test pass/fail tables
- Full failure-handling matrix with implementation status
- Power state boundary table with exact spec values
- Power and thermal estimate summary
- Interface documentation for HW-1 and HW-3
- Honest hardware gap list (see Section 12 of this README)

---

## 9. Test Results Summary

| Suite | File | Tests | Status |
|---|---|---|---|
| Encryption daemon | test_encryption_daemon.py | 29 | All passing |
| Boot sequence | test_boot_sequence.py | 31 | All passing |
| Watchdog | test_watchdog.py | 14 | All passing |
| Power management | test_power_management.py | 45 | All passing |
| **Total** | | **119** | **All passing** |

Run the full suite:

```bash
pytest tests/ -v
```

Expected output:

```
119 passed in 0.08s
```

---

## 10. Interfaces Exposed to Other Tracks

These are the stable public interfaces for Day 5 cross-track integration. Do not change signatures without coordinating with HW-1 and HW-3.

### For HW-1 (camera and audio daemons)

```python
from encryption.daemon import EncryptionDaemon

daemon = EncryptionDaemon(dik, upk)
record = daemon.encrypt(raw_bytes)   # the only way to produce an EncryptedRecord
```

HW-1 hands raw frames and audio buffers to `encrypt()` before any disk write. This is HW-1's Day 3 dependency — it was ready at end of Day 1 of this track.

### For HW-3 (storage manager)

```python
from storage.storage_writer import write_record
from encryption.daemon import EncryptedRecord

write_record(record, "/vault/YYYY-MM-DD/filename.bin")

# Serialized format (for HW-3 to write or read back)
raw = record.to_bytes()
restored = EncryptedRecord.from_bytes(raw)
```

Wire format: binary, `CHRONIS_ENC_V1\x00` magic header followed by five length-prefixed fields (ephemeral public key, outer nonce, outer ciphertext, DIK signature, date string).

### For HW-1 (Day 5 — power daemon capping vs. capture-intensity state machine)

```python
from power.power_management_daemon import PowerManagementDaemon, PowerState

daemon = PowerManagementDaemon(adc_read_fn, charging_detected_fn, notify_fn, log_fn)
state = daemon.tick()                   # call periodically
restrictions = daemon.get_restrictions()
restrictions.camera_max_level           # None = off, int = max L-level cap
restrictions.wifi_enabled               # bool
restrictions.sync_enabled               # bool
```

The "lower of the two always wins" conflict case (power daemon ceiling vs. HW-1 state machine ceiling) is the Day 5 integration test. The power daemon caps; it does not replace HW-1's decision.

### For HW-3 (cloud gateway)

The DIK's Ed25519 signing scheme produces 64-byte signatures over the ECIES envelope. The `ServerTransportKey` (ephemeral X25519) is generated in `encryption/keys.py`. Wire-up to the gateway happens on HW-3 Day 4 — the generation logic is complete on this side.

---

## 11. Component Spec List

Locked part numbers (no pricing, datasheets only):

| Part | Role |
|---|---|
| ICM-42688-P | Motion sensor (IMU) |
| MAX30102 | Heart-rate and PPG sensor |
| ATECC608B | Security and crypto chip |
| IMX219 | Camera sensor |
| DS3231-class | Real-time clock backup |
| Radxa Zero 3W | Main compute board (RK3566 SoC) |

---

## 12. Hardware Gap List

The following cannot be validated without real hardware. This list is not a deficiency of the sprint — it is an honest record of what simulation cannot prove.

**Cryptographic and security**
- Real ATECC608B timing: key generation and signing latency vs. the mock's instant software responses. Daemon startup time will differ.
- ATECC608B I2C address (default 0x60) — must be verified against all other bus occupants once wired together.
- Secure element provisioning: burning the DIK into the chip's protected key slot is a one-time hardware operation with specific ATECC608B command sequences not modeled here.

**Boot sequence**
- I2C and SPI bus address conflicts between ICM-42688-P, MAX30102 (0x57), ATECC608B (0x60), and DS3231 (0x68). No conflicts on paper; must verify with a logic analyzer on real hardware.
- Power-on reset delays: real components have sequencing requirements between rail enable and chip-ready signals. The mock returns `OK` or `FAIL` instantly.
- Clock sync behavior on a fresh device with no stored time and no network.

**Watchdog**
- Real daemon crash vs. liveness timeout: the mock uses synchronous callables. Real daemons need a heartbeat or socket timeout mechanism with different failure semantics.

**Power management**
- All current-draw figures in `power_thermal_estimate.py` are datasheet typical values. Real measurements under sustained load will differ, especially SoC thermal throttling.
- The LiPo discharge curve is a generic approximation. Actual cell behavior depends on temperature, age, and C-rate.
- Coulomb counting accuracy requires hardware fuel gauge or continuous ADC integration — not modeled.

**Enclosure**
- Real thermal behavior in a sealed enclosure under sustained L3-L5 load.
- Physical wearability, comfort, strap ergonomics.
- Camera lens protrusion depth varies by IMX219 module supplier.
- USB-C port clearance against the battery edge connector.
- Actual component weight once parts are sourced.
