#!/usr/bin/env bash
#
# Step 2 — build the seasonal county-level SBP supplemental report.
#
# Edit the CONFIG block, then run:  ./run_seasonal_report.sh
#
set -euo pipefail

# ---------------------------------------------------------------- CONFIG ----

# Athena database / environment: pge_stage | pge_uat | pge  (pge == prod)
DATABASE="pge"

# Season: Spring | Summer | Fall | Winter | All
SEASON="Winter"

# Batches to include: short batch NUMBERS are enough (full names also work).
# Each one is looked up in accountbillinglog and shown for confirmation before
# the report runs. Add or remove lines as needed.
BATCH_IDS=(
  #"252882"

# below is pge_stage
'azkaban_PGE_on_demand_batch_operation_224412'
'azkaban_PGE_on_demand_batch_operation_224437'
'azkaban_PGE_on_demand_batch_operation_224448'
'azkaban_PGE_on_demand_batch_operation_224465'
'azkaban_PGE_on_demand_batch_operation_224531'
)

# Set to "true" to skip the confirmation prompt and use every batch found.
# Required for unattended runs, where there is no terminal to answer the prompt.
AUTO_CONFIRM="false"

# Bill year. Leave empty to auto-derive the report year (current year - 1, e.g. 2026 - 1 = 2025 OR "2025,2026").
BILL_YEARS=""

# Column delimiter for the .txt output: tab | comma | pipe | semicolon
DELIMITER="tab"

# Set to "true" to drop the column header row from the .txt output.
NO_HEADER="false"

# Date stamp in the output filename: SBP_Supplemental_<date>.txt
# %Y%m%d -> yyyymmdd (default).  Use %Y%d%m for yyyyddmm.
FILE_DATE_FORMAT="%Y%m%d"

# Set to "true" to write only the local copy and skip the S3 upload.
SKIP_UPLOAD="false"

# ------------------------------------------------------------ END CONFIG ----

cd "$(dirname "$0")"

PYTHON="./venv/bin/python"
[[ -x "$PYTHON" ]] || PYTHON="python3"

ARGS=(--database "$DATABASE" --season "$SEASON")
for batch_id in "${BATCH_IDS[@]}"; do
  ARGS+=(--batch-id "$batch_id")
done
[[ -n "$BILL_YEARS" ]] && ARGS+=(--bill-years "$BILL_YEARS")
ARGS+=(--delimiter "$DELIMITER" --file-date-format "$FILE_DATE_FORMAT")
[[ "$NO_HEADER" == "true" ]] && ARGS+=(--no-header)
[[ "$SKIP_UPLOAD" == "true" ]] && ARGS+=(--no-upload)
[[ "$AUTO_CONFIRM" == "true" ]] && ARGS+=(--yes)

# Pass through extra flags, e.g. ./run_seasonal_report.sh --print-sql
exec "$PYTHON" generate_seasonal_report.py "${ARGS[@]}" "$@"
