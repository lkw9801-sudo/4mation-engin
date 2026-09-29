#!/bin/bash
# Build the deliverable ZIP (source, tests, benchmarks, results; no build artefacts)
set -e
cd "$(dirname "$0")/.."
OUT=${1:-4mation-engine-v2.zip}
rm -f "$OUT"
zip -r -q "$OUT" 4mation-engine \
  -x "*/__pycache__/*" "*.pyc" "*/_core.so" "*/_core.dll" "*.tmp" "*/solve_runs/*.log" "*/solve_runs/*.err" \
     "*/solve_runs/*.sh"
echo "$OUT"
