# task3-o-p-timing-modules

Team B — Output & Timing Modules, Chronis Hardware Task #3.

Two brand-new firmware modules built from zero (LED controller, OLED
display manager) plus NTP/RTC time sync — none of these existed after
Tasks 1 or 2. This repo carries Task 1's foundation (mock hardware layer,
sensor/security/connectivity tracks) alongside them because later days
(Day 4) wire the new modules into that same mock stack — see
`CHRONIS_Hardware_Task3.md` for the full sprint brief.

**253 tests passing: 232 from Task 1's foundation (3 tracks + Day 5
integration) + 21 from Task 3 Day 1 (LED controller).**

## Quick Start

```bash
pip install -r requirements.txt pytest
bash run_all_tracks.sh
```

## Repository Structure
```
task3-o-p-timing-modules/
├── hw-track-1-sensors/          Task 1 foundation (74 tests)
├── hw-track-2-security-boot/    Task 1 foundation (119 tests)
├── hw-track-3-connectivity/     Task 1 foundation (39 tests)
├── integration/                 Task 1 Day 5 cross-track integration (10 tests)
├── output-timing-modules/       Team B, Task 3 — LED, OLED, NTP (this sprint)
│   ├── led/                     Day 1 — LED controller state machine
│   └── tests/
├── docs/                        Readiness reports from Task 1
└── run_all_tracks.sh
```

## Team B — Task 3 Progress

- **Day 1 (done)**: LED controller — 10 named automatic states (spec text
  says twelve; only 10 are actually enumerated in the spec, flagged
  rather than padded), the two-state unsuppressible-alert rule
  (tamper alert + kill-switch confirmation), and the 10pm-dim/11pm-off
  sleep schedule with a charging override. 21 tests passing.
- Day 2 (OLED display manager) — not started.
- Day 3 (voice-gated wake/sleep + NTP time sync) — not started.
- Day 4 (consolidation + cross-module wiring) — not started.
