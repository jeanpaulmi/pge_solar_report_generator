#!/usr/bin/env bash
#
# Check that billing batches were created, and get their full names for
# run_seasonal_report.sh. Output prints to the terminal only.
#
# Edit the CONFIG block, then run:  ./run_batch_id_name.sh
#
set -euo pipefail

# ---------------------------------------------------------------- CONFIG ----

# Athena database / environment: pge_stage | pge_uat | pge  (pge == prod)
DATABASE="pge"

# Batch numbers (or name fragments) to look up. Add or remove lines as needed.
BATCH_IDS=(
  "252882"
)

# ------------------------------------------------------------ END CONFIG ----

cd "$(dirname "$0")"

PYTHON="./venv/bin/python"
[[ -x "$PYTHON" ]] || PYTHON="python3"

ARGS=(--database "$DATABASE")
for batch_id in "${BATCH_IDS[@]}"; do
  ARGS+=(--batch-id "$batch_id")
done

# Pass through extra flags, e.g. ./run_batch_id_name.sh --print-sql
exec "$PYTHON" batch_id_name.py "${ARGS[@]}" "$@"
