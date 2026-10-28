#!/usr/bin/env python3
"""Check that billing batches were created in accountbillinglog.

For each batch id, prints the distinct contract count and the full batch name
to the terminal, then prints a BATCH_IDS block ready to paste into
``run_seasonal_report.sh``. Nothing is written to disk or S3.

Exits 2 if any batch id matched no rows.

Configure and run it through ``run_batch_id_name.sh``.
"""

from __future__ import annotations

import argparse
import sys

import athena_utils as au
import batch_lookup as bl


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        required=True,
        help="Athena database: pge_stage, pge_uat, or pge (prod)",
    )
    parser.add_argument(
        "--batch-id",
        action="append",
        required=True,
        help="Batch number or name fragment, e.g. 252721. Repeat for several.",
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

    database = au.validate_database(args.database)
    batch_ids = [bl.validate_batch_id(b) for b in args.batch_id]

    sql = au.load_sql(
        "batch_id_name.sql",
        {"database": database, "batch_filter": bl.build_filter(batch_ids)},
    )

    if args.print_sql:
        print(sql)
        return 0

    print(f"[config] database  : {database}")
    print(f"[config] batch ids : {', '.join(batch_ids)}")

    session = au.aws_session(auto_login=not args.no_auto_login)
    matches, missing = bl.lookup(session, database, batch_ids)
    bl.print_matches(matches, missing)

    if matches:
        print("\n# paste into run_seasonal_report.sh, or just use the batch numbers there")
        print("BATCH_IDS=(")
        for match in matches:
            print(f'  "{match.name}"')
        print(")")

    if missing:
        print(f"\n[done]   missing: {', '.join(missing)}")
        return 2

    print(f"\n[done]   {len(matches)} batch(es) found")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (au.AthenaQueryError, ValueError) as exc:
        print(f"[error]  {exc}", file=sys.stderr)
        sys.exit(1)
