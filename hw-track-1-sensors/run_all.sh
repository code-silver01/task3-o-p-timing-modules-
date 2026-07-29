#!/bin/bash
# Run all HW-1 checks in sequence.
# Usage: bash run_all.sh
set -e
cd "$(dirname "$0")"

# Portable python detection (some systems only have python3)
PY=$(command -v python3 || command -v python)

echo "============================================"
echo "  Chronis HW-1 — Full Verification Run"
echo "============================================"
echo "Using interpreter: $PY"
echo ""

echo ">>> Step 1: Running test suite..."
"$PY" -m pytest tests/ -v
echo ""

echo ">>> Step 2: Generating synthetic traces..."
(cd traces && "$PY" trace_generator.py)
echo ""

echo ">>> Step 3: Running extended simulation..."
"$PY" state_machine/extended_run.py
echo ""

echo "============================================"
echo "  All checks passed."
echo "============================================"
