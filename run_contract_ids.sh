#!/usr/bin/env bash
#
# Step 1 — pull contract ids from Athena.
#
# Edit the CONFIG block, then run:  ./run_contract_ids.sh
#
set -euo pipefail

# ---------------------------------------------------------------- CONFIG ----

# Athena database / environment: pge_stage | pge_uat | pge  (pge == prod)
DATABASE="pge"

# Contract start year floor. Leave empty to auto-derive (current year - 1, e.g 2026 - 1 = 2025).
REPORT_YEAR=""

# How many CSV files to split the contract ids across.
#   1 = a single file (default)
#   2 = two files of roughly equal size, 3 = three, and so on.
# Any remainder goes to the earliest files (101 ids over 2 -> 51 + 50).
PARTITIONS="1"

# Set to "true" to write only the local copy and skip the S3 upload.
SKIP_UPLOAD="false"

# ------------------------------------------------------------ END CONFIG ----

cd "$(dirname "$0")"

PYTHON="./venv/bin/python"
[[ -x "$PYTHON" ]] || PYTHON="python3"

ARGS=(--database "$DATABASE")
[[ -n "$REPORT_YEAR" ]] && ARGS+=(--report-year "$REPORT_YEAR")
[[ -n "$PARTITIONS" ]] && ARGS+=(--partitions "$PARTITIONS")
[[ "$SKIP_UPLOAD" == "true" ]] && ARGS+=(--no-upload)

# Pass through extra flags, e.g. ./run_contract_ids.sh --print-sql
exec "$PYTHON" get_contract_ids.py "${ARGS[@]}" "$@"
