#!/usr/bin/env python3
"""Step 2: build the seasonal county-level SBP supplemental report from Athena.

Batch ids may be given as short batch numbers (e.g. 252882) or as full batch
names. Either way they are looked up in accountbillinglog first, shown with
their contract counts, and confirmed at the terminal before the report runs.

Writes an unquoted, delimited text file to:
  s3://<bucket>/<prefix>/<season>_report_<datetime>/SBP_Supplemental_<date>.txt
  ./output/<season>_report_<datetime>/SBP_Supplemental_<date>.txt

Configure and run it through ``run_seasonal_report.sh``.
"""

from __future__ import annotations

import argparse
import contextlib
import sys
from datetime import datetime

import athena_utils as au
import batch_lookup as bl
from config import get_settings

SEASONS = ("Spring", "Summer", "Fall", "Winter", "All")



def normalize_season(value: str) -> str:
    for season in SEASONS:
        if value.strip().lower() == season.lower():
            return season
    raise ValueError(f"season must be one of {SEASONS}, got {value!r}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        required=True,
        help="Athena database: pge_stage, pge_uat, or pge (prod)",
    )
    parser.add_argument(
        "--season",
        required=True,
        help="Spring, Summer, Fall, Winter, or All",
    )
    parser.add_argument(
        "--batch-id",
        dest="batch_ids",
        action="append",
        required=True,
        metavar="BATCH_ID",
        help="Batch number (e.g. 252882) or full batch name. Repeat for several.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt and use every batch found.",
    )
    parser.add_argument(
        "--no-resolve",
        action="store_true",
        help="Use --batch-id values verbatim: no lookup, no prompt.",
    )
    parser.add_argument(
        "--bill-years",
        default=None,
        help="Comma separated bill years. Defaults to the report year (current year - 1).",
    )
    parser.add_argument(
        "--delimiter",
        default="tab",
        help="Column delimiter for the .txt output: tab, comma, pipe, semicolon, "
        "an escape such as '\\t', or a literal character (default: tab).",
    )
    parser.add_argument(
        "--no-header",
        action="store_true",
        help="Omit the column header row from the .txt output.",
    )
    parser.add_argument(
        "--file-date-format",
        default="%Y%m%d",
        help="strftime format for the date in the filename (default: %%Y%%m%%d).",
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
    season = normalize_season(args.season)
    delimiter = au.resolve_delimiter(args.delimiter)

    if args.bill_years:
        years = [int(y.strip()) for y in args.bill_years.split(",") if y.strip()]
    else:
        years = [au.report_year()]

    batch_ids = [bl.validate_batch_id(b) for b in args.batch_ids if b.strip()]
    if not batch_ids:
        raise ValueError("at least one --batch-id is required")

    session = None
    batch_names = batch_ids

    if not args.no_resolve:
        # Resolve the batch numbers to full batch names and confirm them before
        # paying for the report query. With --print-sql the lookup still has to
        # run (the names go into the SQL), so its output is pushed to stderr to
        # keep stdout pipeable.
        with contextlib.redirect_stdout(sys.stderr if args.print_sql else sys.stdout):
            session = au.aws_session(auto_login=not args.no_auto_login)
            print(f"[batch]  looking up {len(batch_ids)} batch id(s) in accountbillinglog ...")
            matches, missing = bl.lookup(session, database, batch_ids)
            bl.print_matches(matches, missing)

            if not matches:
                raise au.AthenaQueryError(
                    f"no batch found for {', '.join(batch_ids)} in "
                    f"{database}.accountbillinglog; nothing to report on"
                )

            batch_names = [match.name for match in matches]

            if not args.print_sql:
                question = (
                    f"\nRun the {season} report on {len(batch_names)} batch(es)"
                    + (f", ignoring {len(missing)} not found" if missing else "")
                    + "?"
                )
                if not bl.confirm(question, assume_yes=args.yes):
                    print("[done]   cancelled, no report written")
                    return 1

    sql = au.load_sql(
        "seasonal_county_stats.sql",
        {
            "database": database,
            "season": season,
            "bill_years": ", ".join(str(y) for y in years),
            "batch_ids": au.quoted_sql_list(batch_names),
        },
    )

    if args.print_sql:
        print(sql)
        return 0

    print(f"[config] database   : {database}")
    print(f"[config] season     : {season}")
    print(f"[config] bill years : {', '.join(str(y) for y in years)}")
    if season == "Winter":
        print(
            "[config]              Winter = Dec of each bill year + Jan/Feb of "
            f"the year after ({', '.join(f'{y}-12' for y in years)}"
            f" + {', '.join(f'{y + 1}-01/02' for y in years)})"
        )
    print(f"[config] delimiter  : {delimiter!r}")
    print(f"[config] batches    : {len(batch_names)}")
    for batch_name in batch_names:
        print(f"[config]              {batch_name}")

    stamp = au.run_stamp()
    folder = f"{season.lower()}_report_{stamp}"
    filename = f"SBP_Supplemental_{datetime.now().strftime(args.file_date_format)}.txt"
    local_path = au.OUTPUT_DIR / folder / filename

    if session is None:
        session = au.aws_session(auto_login=not args.no_auto_login)
    output_location = au.run_query(session, sql, database)

    rows = au.fetch_result_rows(session, output_location)
    try:
        header = next(rows)
    except StopIteration:
        raise au.AthenaQueryError("Athena returned an empty result file")

    count = au.write_delimited(
        local_path,
        rows,
        delimiter=delimiter,
        header=None if args.no_header else header,
    )

    if count == 0:
        print("[warn] query returned no county rows", file=sys.stderr)

    if not args.no_upload:
        bucket = args.s3_bucket or settings.REPORT_S3_BUCKET
        prefix = (args.s3_prefix or settings.REPORT_S3_PREFIX).strip("/")
        au.upload_file(
            session, local_path, f"s3://{bucket}/{prefix}/{folder}/{filename}"
        )

    print(f"[done]   {count} counties in {filename}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (au.AthenaQueryError, ValueError) as exc:
        print(f"[error]  {exc}", file=sys.stderr)
        sys.exit(1)
