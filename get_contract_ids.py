#!/usr/bin/env python3
"""Step 1: pull active NEM3 residential EELEC contract ids from Athena.

Writes a headerless, unquoted single-column CSV to:
  s3://<bucket>/<prefix>/contract_ids_<datetime>/contract_ids_<datetime>.csv
  ./output/contract_ids_<datetime>/contract_ids_<datetime>.csv

Configure and run it through ``run_contract_ids.sh``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import athena_utils as au
from config import get_settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        required=True,
        help="Athena database: pge_stage, pge_uat, or pge (prod)",
    )
    parser.add_argument(
        "--report-year",
        type=int,
        default=None,
        help="Contract start year floor. Defaults to the current year minus 1.",
    )
    parser.add_argument("--s3-bucket", default=None, help="Override the output bucket.")
    parser.add_argument("--s3-prefix", default=None, help="Override the output key prefix.")
    parser.add_argument(
        "--no-upload",
        action="store_true",
        help="Write the local copy only; skip the S3 upload.",
    )
    parser.add_argument(
        "--no-auto-login",
        action="store_true",
        help="Fail on expired credentials instead of running 'aws sso login'.",
    )
    parser.add_argument(
        "--print-sql",
        action="store_true",
        help="Print the rendered SQL and exit without running it.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = get_settings()

    database = au.validate_database(args.database)
    year = args.report_year if args.report_year is not None else au.report_year()
    stamp = au.run_stamp()

    sql = au.load_sql(
        "contract_ids.sql",
        {"database": database, "report_year": year},
    )

    if args.print_sql:
        print(sql)
        return 0

    print(f"[config] database    : {database}")
    print(f"[config] report year : {year} (contract_start_date >= {year}-01-01)")

    folder = f"contract_ids_{stamp}"
    filename = f"contract_ids_{stamp}.csv"
    local_path = au.OUTPUT_DIR / folder / filename

    session = au.aws_session(auto_login=not args.no_auto_login)
    output_location = au.run_query(session, sql, database)

    rows = au.fetch_result_rows(session, output_location)
    try:
        next(rows)  # drop the header row Athena always emits
    except StopIteration:
        print("[warn] query returned no rows at all", file=sys.stderr)

    # Single column, no header, no quotes.
    count = au.write_delimited(local_path, ([r[0]] for r in rows if r))

    if count == 0:
        print("[warn] no contract ids matched the filters", file=sys.stderr)

    if not args.no_upload:
        bucket = args.s3_bucket or settings.REPORT_S3_BUCKET
        prefix = (args.s3_prefix or settings.REPORT_S3_PREFIX).strip("/")
        au.upload_file(
            session, local_path, f"s3://{bucket}/{prefix}/{folder}/{filename}"
        )

    print(f"[done]   {count} contract ids")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (au.AthenaQueryError, ValueError) as exc:
        print(f"[error]  {exc}", file=sys.stderr)
        sys.exit(1)
