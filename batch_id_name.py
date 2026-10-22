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
import re
import sys

import athena_utils as au


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


def validate_batch_id(batch_id: str) -> str:
    value = batch_id.strip()
    # Letters, digits and underscores only: keeps LIKE wildcards and quotes out.
    if not re.fullmatch(r"[A-Za-z0-9_]+", value):
        raise ValueError(f"invalid batch id: {batch_id!r}")
    return value


def main() -> int:
    args = parse_args()

    database = au.validate_database(args.database)
    batch_ids = [validate_batch_id(b) for b in args.batch_id]

    sqls = {
        b: au.load_sql("batch_id_name.sql", {"database": database, "batch_id": b})
        for b in batch_ids
    }

    if args.print_sql:
        print("\n\n".join(sqls.values()))
        return 0

    print(f"[config] database  : {database}")
    print(f"[config] batch ids : {', '.join(batch_ids)}")

    session = au.aws_session(auto_login=not args.no_auto_login)

    found: list[tuple[str, str]] = []  # (count, batch name)
    missing: list[str] = []

    for batch_id, sql in sqls.items():
        output_location = au.run_query(session, sql, database)
        rows = au.fetch_result_rows(session, output_location)
        next(rows, None)  # drop the header row Athena always emits

        matches = [(r[0], r[1]) for r in rows if r]
        if not matches:
            print(f"[warn]   no batch matching {batch_id!r}", file=sys.stderr)
            missing.append(batch_id)
        elif len(matches) > 1:
            print(
                f"[warn]   {batch_id!r} matched {len(matches)} batches; check which one you want",
                file=sys.stderr,
            )
        found.extend(matches)

    print()
    if found:
        width = max(len(name) for _, name in found)
        print(f"{'batch':<{width}}  contract_id_count")
        print(f"{'-' * width}  -----------------")
        for count, name in found:
            print(f"{name:<{width}}  {count:>17}")

        print("\n# paste into run_seasonal_report.sh")
        print("BATCH_IDS=(")
        for _, name in found:
            print(f'  "{name}"')
        print(")")

    if missing:
        print(f"\n[done]   missing: {', '.join(missing)}")
        return 2

    print(f"\n[done]   {len(found)} batch(es) found")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (au.AthenaQueryError, ValueError) as exc:
        print(f"[error]  {exc}", file=sys.stderr)
        sys.exit(1)
