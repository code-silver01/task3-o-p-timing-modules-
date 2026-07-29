#!/bin/bash
# Run Task 1's foundation tracks + Team B's Task 3 output/timing modules.
set -e
cd "$(dirname "$0")"
PY=$(command -v python3 || command -v python)

echo "════════ HW-1: Sensor & Motion (Task 1 foundation) ════════"
(cd hw-track-1-sensors && "$PY" -m pytest tests/ -q)

echo "════════ HW-2: Security & Boot (Task 1 foundation) ════════"
(cd hw-track-2-security-boot && "$PY" -m pytest tests/ -q)

echo "════════ HW-3: Connectivity & Cloud (Task 1 foundation) ════════"
(cd hw-track-3-connectivity && "$PY" -m pytest tests/ -q)

echo "════════ Team B: Output & Timing Modules (Task 3) ════════"
(cd output-timing-modules && "$PY" -m pytest tests/ -q)

echo "════════ Day 5 (Task 1): Cross-Track Integration ════════"
"$PY" -m pytest integration/test_day5_integration.py -q

echo ""
echo "ALL GREEN: 74 + 119 + 39 + 21 = 253 tests"
