# task3-o-p-timing-modules

Team B — Output & Timing Modules, Chronis Hardware Task #3.

Three brand-new firmware modules built from zero (LED controller, OLED display manager, NTP/RTC time sync) plus a voice-gated wake stub — none of these existed after Tasks 1 or 2. This repo carries Task 1's foundation (mock hardware layer, sensor/security/connectivity tracks) alongside them because Day 4 wires the new modules into that same mock stack and verifies them against the full scenario trace library.

**329 tests passing across the entire repo** — 242 from Tasks 1 & 2 foundation + 87 from Task 3 (this sprint).

---

## Quick Start

```bash
pip install -r requirements.txt
python -m pytest output-timing-modules/tests/ -v          # Task 3 only (87 tests)
python -m pytest hw-track-1-sensors/tests/ -q             # Track 1 foundation (74 tests)
python -m pytest hw-track-2-security-boot/tests/ -q       # Track 2 foundation (119 tests)
python -m pytest hw-track-3-connectivity/tests/ -q         # Track 3 foundation (39 tests)
python -m pytest integration/test_day5_integration.py -q   # Cross-track integration (10 tests)
```

Or run everything at once:

```bash
bash run_all_tracks.sh
```

---

## Repository Structure

```
task3-o-p-timing-modules/
│
├── output-timing-modules/           ← Team B, Task 3 — THIS SPRINT
│   ├── led/                         Day 1 — LED controller state machine
│   │   ├── led_states.py            10 automatic LED states + IDLE_OFF enum
│   │   ├── led_controller.py        Full state machine: triggers, suppression, sleep schedule
│   │   └── mock_led_driver.py       Mock hardware: 12 front-arc LEDs + 3 back zones
│   ├── oled/                        Day 2 — OLED display manager
│   │   ├── oled_states.py           8-level priority stack + ambient mode constants
│   │   ├── oled_controller.py       Priority rendering, privacy pixel, tap-to-wake, insight auto-dismiss
│   │   └── mock_display_buffer.py   Mock hardware: content + brightness + privacy pixel
│   ├── ntp_sync/                    Day 3 — NTP time sync daemon
│   │   ├── ntp_daemon.py            Three-tier drift correction, RTC fallback, phone alerts
│   │   ├── mock_time_source.py      Mock NTP server: deterministic drift injection
│   │   └── drift_log.py             Persistent append-only JSONL drift log
│   ├── voice_wake/                  Day 3 — Voice-gated wake stub
│   │   └── voice_gate.py            Enrollment, fingerprint matching, display wake trigger
│   ├── integration/                 Day 4 — Cross-module wiring
│   │   └── wired_devices.py         WiredOutputDevices: LED + OLED + NTP on the CSE tick
│   └── tests/                       All Task 3 tests (87 total)
│       ├── test_led_controller.py   21 tests — all states, suppression rule, sleep schedule
│       ├── test_oled_controller.py  26 tests — priority stack, ambient, tap-to-wake, privacy pixel
│       ├── test_ntp_sync.py         20 tests — 3 drift tiers, boundaries, RTC fallback, persistent log
│       ├── test_voice_gate.py        7 tests — enrollment, matching, wake trigger
│       └── test_day4_wiring.py      13 tests — 5 scenario traces, timing budget proof
│
├── hw-track-1-sensors/              Task 1 foundation — sensor daemons & CSE (74 tests)
│   ├── daemons/                     MotionDaemon, HeartRateDaemon, WornNotWornDetector, etc.
│   ├── state_machine/               CaptureStateMachine (L0–L5), extended_run driver
│   ├── traces/                      Synthetic scenario traces (JSON)
│   │   ├── idle_dormant.json        Worn, nothing happening, CSE stays L0
│   │   ├── ambient_alone.json       Ambient sound, reaches L1–L2
│   │   ├── active_conversation.json Active dialogue, reaches L4 (Engaged)
│   │   ├── multiparty_highenergy.json  Peak social energy, reaches L5
│   │   └── not_worn_test.json       Device removed — triggers not-worn detection
│   ├── mock_hal/                    Mock hardware abstraction layer
│   └── tests/
│
├── hw-track-2-security-boot/        Task 1 foundation — encryption, boot, storage (119 tests)
│   ├── encryption/                  AES-256 encryption layer
│   ├── boot/                        Secure boot chain
│   ├── storage/                     Append-only permanent record
│   ├── power/                       Power management
│   ├── thermal/                     Thermal monitoring
│   ├── watchdog/                    Watchdog timer
│   └── tests/
│
├── hw-track-3-connectivity/         Task 1 foundation — BLE, cloud, OTA (39 tests)
│   ├── ble_daemon/                  BLE communication daemon
│   ├── cloud_gateway/               Cloud sync gateway
│   ├── ota/                         Over-the-air update system
│   ├── network/                     Network management
│   └── tests/
│
├── integration/                     Cross-track integration (10 tests)
│   ├── test_day5_integration.py     Task 1 Day 5 cross-track integration tests
│   └── power_ceiling_combiner.py    Power ceiling arbitration
│
├── docs/
│   ├── CHRONIS_Hardware_Task3.md    Full sprint brief / specification
│   ├── HARDWARE_READINESS_REPORT.md Hardware readiness assessment
│   └── COMPONENT_SPEC_LIST.md      Component specification index
│
├── requirements.txt                 numpy>=1.24.0, pytest>=7.4.0
├── run_all_tracks.sh                Runs all test suites in sequence
└── .gitignore
```

---

## Test Summary

| Suite | Tests | What it covers |
|---|---|---|
| **Task 3: LED Controller** | 21 | All 10+1 states, suppression rule (tamper + kill-switch unsuppressible), sleep schedule (dim at 10pm, off at 11pm), charging override, safety-critical bypass of night mode |
| **Task 3: OLED Display Manager** | 26 | 8-level priority stack (each level beats the one below it), camera-killed icon lock, insight 60-char limit + 10s auto-dismiss + tap-to-expand, always-on ambient mode at 5 cd/m², status dot cycling every 5s, tap-to-wake (15s then back to ambient), **7-test privacy pixel proof** |
| **Task 3: NTP Time Sync** | 20 | Three drift tiers (slew < 100ms, step 100ms–1s, step+alert > 1s), both boundary values (exactly 100ms, exactly 1s), negative drift, retrospective record adjustment, phone alert, persistent JSONL drift log (survives daemon restart), DS3231 RTC fallback path |
| **Task 3: Voice Gate** | 7 | Enrollment gating, enrolled voice match, noisy-repeat tolerance, other-voice rejection, display wake trigger, pre-enrollment error |
| **Task 3: Day 4 Wiring** | 13 | LED + OLED + NTP wired into Task 1's real pipeline (MotionDaemon, HeartRateDaemon, WornNotWornDetector, CaptureStateMachine), verified against 5 scenario traces (idle_dormant, not_worn_test, ambient_alone, active_conversation, multiparty_highenergy), timing budget proof (every tick < 50ms, well under 500ms CSE cadence) |
| Track 1: Sensors & Motion | 74 | Task 1 foundation |
| Track 2: Security & Boot | 119 | Task 1 foundation |
| Track 3: Connectivity | 39 | Task 1 foundation |
| Cross-track Integration | 10 | Task 1 Day 5 |
| **Total** | **329** | |

---

## Team B — Task 3 Progress

### Day 1 ✅ — LED Controller: Full State Machine
- 10 named automatic states implemented against a mock LED driver (12 front-arc LEDs + 3 separately addressable back zones): charging fill, sync chase, low-battery pulse, new-insight flash, not-worn breathing amber (back zones only), kill-switch confirmation flash, tamper alert pulse, BLE pairing chase, mode-change confirmation flash, and the CSE-level-dependent capture-active dim dot (visible at L4–L5, no LED at L3 and below).
- **Suppression rule**: user can disable every automatic state except tamper alert and kill-switch confirmation flash. Both `suppress()` calls raise `CannotSuppressError`. Unsuppressible states also bypass the night sleep schedule entirely.
- **Sleep schedule**: auto-dim at 10pm, full off at 11pm, resume at 7am. Hours are constructor-configurable. Charging overrides the schedule (LEDs stay active).
- **Spec note**: the spec says "twelve automatic states" but the comma-separated list names 10 distinct animations. This is documented in `led_states.py` rather than padded with invented states.

### Day 2 ✅ — OLED Display Manager: Priority Stack
- 8-level priority stack, highest priority first: tamper alert → BLE pairing QR → camera-killed icon → charging fill → low-battery icon → insight notification → capture-active indicator → idle face.
- **Camera-killed icon** persists until `reset_camera_kill_icon()` (physical slider reset). Calling `clear(CAMERA_KILLED_ICON)` raises `CameraKilledIconLockedError`.
- **Insight notification**: 60-character max (raises `InsightTooLongError`), 10-second auto-dismiss, tap-to-expand.
- **Always-on ambient mode**: 5 cd/m² brightness, cycling status dot (battery → sync → capture, every 5 seconds).
- **Tap-to-wake**: simulated IMU single-tap brings up the full display for 15 seconds, then returns to ambient.
- **Privacy pixel proof**: 7 tests prove the firmware-drawn privacy pixel cannot be disabled through any software path — not through `apply_display_setting()` with any key, not through `set_watchface()` with any name, not through any state transition, not through ambient/awake transitions. It turns off only when `set_camera_active(False)` is called.

### Day 3 ✅ — Voice-Gated Wake + NTP Time Sync
- **Voice gate**: mock fingerprint/embedding enrollment stub using Euclidean distance comparison. Enrolled voice (and noisy repeats within threshold) wakes the display via `trigger_wake()`. Non-matching voices are silently ignored.
- **NTP daemon**: sync-on-WiFi-connect with three-tier drift correction:
  - Drift **< 100ms** → gradual slew, no disruption to existing timestamps, no alert.
  - Drift **100ms–1000ms** → stepped correction, logged, retrospective adjustment of recent sensor records.
  - Drift **> 1000ms** → stepped correction, logged, retrospective adjustment, **plus** alert pushed to phone.
- **Boundary values**: exactly 100ms → step_logged (not slew). Exactly 1000ms → step_logged (not alert).
- **DS3231 RTC fallback**: `boot_without_wifi()` falls back to the battery-backed RTC. NTP sync can proceed normally once WiFi becomes available.
- **Persistent drift log**: append-only JSONL file. Survives daemon restarts (proven by test with two separate DriftLog instances reading the same file).

### Day 4 ✅ — Consolidation + Cross-Module Wiring
- `WiredOutputDevices` class wires LED, OLED, and NTP into the existing mock HAL, ticking on the same 500ms cadence as Task 1's `CaptureStateMachine`.
- Each new module verified against **all five scenario traces** using Task 1's real, already-tested pipeline (not reimplemented):
  - `idle_dormant` — stays L0, no capture indicator, LED at IDLE_OFF.
  - `not_worn_test` — LED shows NOT_WORN_BREATHING_AMBER.
  - `ambient_alone` — reaches L1–L2, OLED capture indicator active.
  - `active_conversation` — reaches L4 (Engaged), LED shows capture dim dot.
  - `multiparty_highenergy` — reaches L5 (Peak), LED shows correct state.
- **Timing proof**: wall-clock measurement of every `on_cse_tick()` call across the busiest trace confirms all ticks complete in < 50ms — well under the 500ms CSE budget.

---

#
