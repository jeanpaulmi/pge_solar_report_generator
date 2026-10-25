#!/usr/bin/env python3
"""Step 1: pull active NEM3 residential EELEC contract ids from Athena.

Writes a headerless, unquoted single-column CSV to:
  s3://<bucket>/<prefix>/contract_ids_<datetime>/contract_ids_<datetime>.csv
  ./output/contract_ids_<datetime>/contract_ids_<datetime>.csv

With --partitions N (N > 1) the ids are split across N near-equal files named
contract_ids_<datetime>_part<i>of<N>.csv in that same folder.

Configure and run it through ``run_contract_ids.sh``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import athena_utils as au
from config import get_settings


def positive_int(value: str) -> int:
    """argparse type for a count that must be 1 or more."""
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"must be a whole number, got {value!r}") from None
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1, got {number}")
    return number


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
    parser.add_argument(
        "--partitions",
        type=positive_int,
        default=1,
        help="Split the contract ids across this many CSV files (default: 1 = one file).",
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

    session = au.aws_session(auto_login=not args.no_auto_login)
    output_location = au.run_query(session, sql, database)

    rows = au.fetch_result_rows(session, output_location)
    try:
        next(rows)  # drop the header row Athena always emits
    except StopIteration:
        print("[warn] query returned no rows at all", file=sys.stderr)

    contract_ids = [row[0] for row in rows if row]
    count = len(contract_ids)

    partitions = args.partitions
    if count == 0:
        print("[warn] no contract ids matched the filters", file=sys.stderr)
        partitions = 1  # still write one (empty) file rather than N of them
    elif partitions > count:
        print(
            f"[warn] --partitions {partitions} exceeds the {count} contract ids "
            f"returned; writing {count} file(s) rather than leaving some empty",
            file=sys.stderr,
        )
        partitions = count

    if partitions > 1:
        print(f"[config] partitions : {partitions}")

    bucket = args.s3_bucket or settings.REPORT_S3_BUCKET
    prefix = (args.s3_prefix or settings.REPORT_S3_PREFIX).strip("/")
    chunks = au.split_evenly(contract_ids, partitions)

    for index, chunk in enumerate(chunks, start=1):
        if partitions == 1:
            filename = f"contract_ids_{stamp}.csv"
        else:
            filename = f"contract_ids_{stamp}_{au.part_label(index, partitions)}.csv"
        local_path = au.OUTPUT_DIR / folder / filename

        # Single column, no header, no quotes.
        au.write_delimited(local_path, ([contract_id] for contract_id in chunk))

        if not args.no_upload:
            au.upload_file(
                session, local_path, f"s3://{bucket}/{prefix}/{folder}/{filename}"
            )

    if partitions == 1:
        print(f"[done]   {count} contract ids")
    else:
        sizes = ", ".join(str(len(chunk)) for chunk in chunks)
        print(f"[done]   {count} contract ids across {partitions} files ({sizes})")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (au.AthenaQueryError, ValueError) as exc:
        print(f"[error]  {exc}", file=sys.stderr)
        sys.exit(1)
