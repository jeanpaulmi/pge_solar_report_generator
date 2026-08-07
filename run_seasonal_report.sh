#!/usr/bin/env bash
#
# Step 2 — build the seasonal county-level SBP supplemental report.
#
# Edit the CONFIG block, then run:  ./run_seasonal_report.sh
#
set -euo pipefail

# ---------------------------------------------------------------- CONFIG ----

# Athena database / environment: pge_stage | pge_uat | pge  (pge == prod)
DATABASE="pge_stage"

# Season: Spring | Summer | Fall | Winter | All
SEASON="Fall"

# Azkaban batch ids to include. Add or remove lines as needed.
BATCH_IDS=(
  "azkaban_PGE_on_demand_batch_operation_224412"
  "azkaban_PGE_on_demand_batch_operation_224437"
  "azkaban_PGE_on_demand_batch_operation_224448"
  "azkaban_PGE_on_demand_batch_operation_224465"
  "azkaban_PGE_on_demand_batch_operation_224531"
)

# Bill years. Leave empty to auto-derive (current year - 1, current year).
BILL_YEARS=""

# Column delimiter for the .txt output.
DELIMITER=","

# Set to "true" to drop the column header row from the .txt output.
NO_HEADER="false"

# Date stamp in the output filename: SBP_Suplemental_<date>.txt
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

# Pass through extra flags, e.g. ./run_seasonal_report.sh --print-sql
exec "$PYTHON" generate_seasonal_report.py "${ARGS[@]}" "$@"
