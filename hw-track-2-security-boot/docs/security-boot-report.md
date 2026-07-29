# Security & Boot Logic — Consolidated Report
## Chronis HW-Track-2, Day 4

**Sprint:** Hardware Task #1, 4-Day Simulation-First Firmware Sprint
**Track:** HW-2 — Security & Boot Logic
**Component list (locked):** ICM-42688-P, MAX30102, ATECC608B, IMX219, DS3231-class, Radxa Zero 3W

---

## 1. Encryption Daemon — Day 1 Results

**Test file:** `tests/test_encryption_daemon.py` — **29 tests, all passing**

### What was built
- `mock_crypto/crypto_chip.py` — mock ATECC608B API (Ed25519 + X25519 via `cryptography` library). Explicit `UNAVAILABLE` state (Rule 3). Swap this file for real I2C driver when hardware arrives; nothing above it changes.
- `encryption/keys.py` — DIK (Ed25519, private key bytes never exposed via public API), DSK (HKDF-derived daily from DIK + date, not stored), UPK (X25519 public key), ServerTransportKey (ephemeral X25519).
- `encryption/daemon.py` — `EncryptionDaemon.encrypt()` is the sole producer of `EncryptedRecord`. Factory token pattern: `EncryptedRecord.__init__` requires a module-private sentinel object; direct construction without it raises `RuntimeError` immediately. Two-layer encryption: AES-256-GCM with DSK (layer 1), ECIES/X25519 + AES-256-GCM with UPK (layer 2), Ed25519 signature with DIK over outer envelope.
- `storage/storage_writer.py` — `write_record()` accepts only `EncryptedRecord` (`isinstance` enforced), rejects raw bytes/strings/dicts/duck-typed lookalikes. Refuses to overwrite existing paths (Rule 2).

### Verified properties
| Property | Status |
|---|---|
| Raw bytes/strings/dicts rejected by write_record() | PASS |
| EncryptedRecord direct construction fails | PASS |
| write_record() never overwrites | PASS |
| Full encrypt→decrypt roundtrip | PASS |
| Tampered ciphertext fails signature verification | PASS |
| Wrong UPK private key cannot decrypt | PASS |
| DSK differs across dates, identical within a date | PASS |
| DIK exposes no raw private key via public API | PASS |

### Interface published to HW-1 / HW-3
- `EncryptionDaemon(dik, upk).encrypt(plaintext: bytes) -> EncryptedRecord`
- `write_record(record: EncryptedRecord, path: str) -> None`
- `EncryptedRecord.to_bytes() -> bytes` — wire format for HW-3 storage manager
- `EncryptedRecord.from_bytes(data: bytes) -> EncryptedRecord` — deserialization for HW-3

---

## 2. Boot Sequence & Failure Handling — Day 2 Results

**Test file:** `tests/test_boot_sequence.py` — **31 tests, all passing**

### Boot order implemented (exact spec, do not reorder)
```
power_rails → security_chip → clock_sync → storage → motion_sensor →
heart_rate_sensor → camera → display → status_led → bluetooth → wifi
```

### Failure table results

| Component | Required behavior | Implemented | Test |
|---|---|---|---|
| Security chip | SYSTEM HALT, alert phone | HALT path, halts immediately, notifies | PASS |
| Storage | SYSTEM HALT, alert phone | HALT path, halts immediately, notifies | PASS |
| Motion sensor | Degraded boot, audio-only, notify | DEGRADED, continues, notifies | PASS |
| Heart-rate sensor | Degraded boot, no HR features, notify | DEGRADED, continues, notifies | PASS |
| Camera | Audio-only boot, notify | DEGRADED, continues, notifies | PASS |
| Display | Continue, LED takes over | NORMAL, logs only, no phone notify | PASS |
| Status LED | Continue, log only | NORMAL, logs only | PASS |
| Bluetooth | Continue, fall back to WiFi, log, display icon | NORMAL, display event fired | PASS |
| WiFi | Continue, store locally, log | NORMAL, logs only | PASS |

**Key invariant maintained:** HALT rows (`security_chip`, `storage`) use a separate code path from all `DEGRADED`/`NORMAL` rows. A broken display cannot accidentally share a code path with a security chip failure.

---

## 3. Watchdog Daemon — Day 3 Results

**Test file:** `tests/test_watchdog.py` — **14 tests, all passing**

### What was built
- `watchdog/watchdog_daemon.py` — `WatchdogDaemon` polls registered daemons.
  - **encryption_daemon failure → SYSTEM HALT** (Rule 1: every other daemon depends on it).
  - **All other daemon failures → isolated restart** of that daemon only; rest of system unaffected.
  - Sweep stops immediately on HALT, so daemons registered after encryption_daemon are not checked.

### Verified properties
| Property | Status |
|---|---|
| Encryption daemon dead → HALT fires | PASS |
| Encryption daemon UNAVAILABLE → HALT fires | PASS |
| Encryption daemon failure → no restart attempted | PASS |
| Encryption daemon failure stops sweep | PASS |
| Other daemon dead → isolated restart | PASS |
| Other daemon failure → no HALT | PASS |
| Other daemon failure → remaining daemons still checked | PASS |
| Multiple non-encryption failures → all restarted independently | PASS |

---

## 4. Power Management Daemon — Day 3 Results

**Test file:** `tests/test_power_management.py` — **59 tests, all passing**

### What was built
- `power/power_management_daemon.py` — `PowerManagementDaemon` reads mock ADC voltage, applies discharge curve lookup table, enforces four power states as restriction caps on top of HW-1's capture-intensity state machine.
- `power/battery_health.py` — Coulomb counting; flags replacement at ≥ 500 charge cycles.
- `power/power_thermal_estimate.py` — **UNVERIFIED PLANNING ESTIMATE** — datasheet-based current draw per component at L0–L5.

### Power state boundaries (spec-exact)

| State | Range | Camera | LED | Audio | Sync | WiFi | BLE |
|---|---|---|---|---|---|---|---|
| Full Active | > 40% | L5 | 100% | L5 | on | on | normal |
| Conservation | 20–40% (≥ 20) | L4 | 50% | L4 | throttled | on | normal |
| Critical | < 20% (≥ 5) | L3 | 20% | L3 | off | on | normal |
| Emergency | < 5% | off | pulse | ring-buf | off | off | beacon only |

Note on boundary values: "Below 20%" = `< 20`, so 20% exactly is Conservation. "Below 5%" = `< 5`, so 5% exactly is Critical.

### Verified properties
| Property | Status |
|---|---|
| All four states enforce correct restriction sets | PASS |
| Boundary values 40%, 20%, 5% placed correctly | PASS |
| Conservation entry notifies phone exactly once | PASS |
| Critical notifies phone on entry | PASS |
| Emergency notifies phone urgently on entry | PASS |
| Charging detected → CHARGING state + animation | PASS |
| Battery replacement flag at ≥ 500 cycles, not before | PASS |
| Daily power report JSON has correct schema | PASS |

### Power/thermal estimate summary (UNVERIFIED — planning only)

| Level | Est. Total (mA) | Est. Power (mW) | Est. Runtime (h) | Thermal Warning |
|---|---|---|---|---|
| L0 | ~200 | ~741 | ~15 h | no |
| L3 | ~1053 | ~3896 | ~2.8 h | YES |
| L5 | ~1663 | ~6152 | ~1.8 h | YES |

L3 and above exceed the 3 W thermal ceiling — active heat management or duty-cycling required.

---

## 5. Enclosure — Day 3 Deliverable

**File:** `enclosure/enclosure_spec.md`

First-pass enclosure envelope derived from public datasheets: **90 mm × 68 mm × 18 mm** target.
Estimated weight ~85 g (unvalidated). Thermal flag: sustained L4–L5 operation likely requires
thermally conductive shell material or thermal pad on SoC. Full details in the spec file.

---

## 6. Honest Gap List — What Cannot Be Validated Without Real Hardware

This list is the primary deliverable of Day 4. Nothing below is "done" until validated on hardware.

### Cryptographic / security
- Real ATECC608B timing behavior (key generation, signing latency) vs. the mock's instant responses. The mock uses `os.urandom` and software Ed25519; the chip has hardware RNG and a distinct timing profile that will affect daemon startup time.
- ATECC608B I2C address (default 0x60) — must be confirmed against the full I2C bus occupant list once all components are wired.
- Secure element provisioning flow (burning the DIK into the chip's protected slot) — the mock generates and holds the key in RAM; real provisioning is a one-time hardware operation with specific ATECC608B command sequences.

### Boot sequence
- Actual I2C/SPI bus address conflicts between ICM-42688-P (SPI/I2C), MAX30102 (I2C 0x57), ATECC608B (I2C 0x60), DS3231 (I2C 0x68) — no conflicts on paper, but must verify on the real bus with a logic analyzer.
- Real component power-on timing (sequencing delays between power rails and chip ready signals). The mock returns `OK` or `FAIL` instantly; real hardware has power-on reset delays that may require sleep/poll loops in the boot sequence.
- Clock sync behavior when DS3231 has no stored time (fresh device, no network yet).

### Watchdog
- Real daemon crash vs. liveness-check timeout: the mock uses a synchronous `Callable[[], DaemonStatus]`; real daemons may need a heartbeat/socket timeout mechanism, which has different failure semantics.

### Power management
- All current-draw figures in `power_thermal_estimate.py` are datasheet typical values. Real measurements under sustained load will differ, particularly for the SoC (RK3566 thermal throttling behavior is not modeled).
- Battery discharge curve: the LiPo discharge lookup table is a generic curve. The actual cell's curve depends on temperature, age, and C-rate — none of which the mock can represent.
- Coulomb counting accuracy: the mock records discrete `record_discharge()` calls; real Coulomb counting requires a hardware fuel gauge or continuous ADC sampling with integration.

### Enclosure
- Real thermal behavior in a sealed enclosure under sustained L4–L5 load.
- Physical wearability, comfort, and strap attachment ergonomics.
- Camera lens protrusion and module depth (varies by IMX219 module supplier).
- USB-C port placement clearance with battery connector.

---

## 7. Cross-Track Interface Status

| Interface | Consumer | Status |
|---|---|---|
| `EncryptionDaemon.encrypt(plaintext) → EncryptedRecord` | HW-1 (camera/audio, Day 3) | Ready — stable interface |
| `write_record(record, path)` | HW-3 (storage manager, Day 1) | Ready — stable interface |
| `EncryptedRecord.to_bytes()` wire format | HW-3 (storage manager) | Ready — documented format |
| `PowerManagementDaemon` public interface | HW-1 (Day 5 integration) | Ready — stable, documented |
| DIK signature scheme / `ServerTransportKey` | HW-3 (cloud gateway, Day 4) | Generation logic built; wire-up pending HW-3 gateway |
| L0–L5 capture-intensity definitions | HW-1 → this track (thermal estimate, power caps) | Stubbed against spec table; update when HW-1 publishes |

---

## 8. Definition of Done — Checklist

- [x] All four Day-1 through Day-4 deliverables exist and pass their test suites (119 tests total, all green)
- [x] Zero violations of Rules 1–4 in this track's code
- [x] `docs/security-boot-report.md` exists with an explicit, honest hardware-dependent gap list
- [x] Every public interface exposed to HW-1/HW-3 is stable and documented
- [x] `pytest tests/ -v` runs clean with no warnings
- [ ] Validated on real hardware (out of scope for this sprint — see gap list above)
