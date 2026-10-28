#!/usr/bin/env python3
"""Resolve short batch numbers to full billing batch names.

Shared by ``generate_seasonal_report.py``, which resolves and confirms batches
before building the report, and ``batch_id_name.py``, which only reports what
it finds. One query covers every batch id passed in.
"""

from __future__ import annotations

import re
import sys
from typing import NamedTuple, Sequence

import athena_utils as au


class BatchMatch(NamedTuple):
    """One row of accountbillinglog grouped by batch name."""

    name: str
    contract_count: str


def validate_batch_id(value: str) -> str:
    """Letters, digits and underscores only, keeping LIKE wildcards and quotes out."""
    text = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9_]+", text):
        raise ValueError(
            f"invalid batch id: {value!r} (letters, digits and underscores only)"
        )
    return text


def build_filter(batch_ids: Sequence[str]) -> str:
    """OR together one LIKE clause per batch id."""
    if not batch_ids:
        raise ValueError("at least one batch id is required")
    return "\n     OR ".join(f"batch LIKE '%{batch_id}%'" for batch_id in batch_ids)


def lookup(
    session, database: str, batch_ids: Sequence[str]
) -> tuple[list[BatchMatch], list[str]]:
    """Return (matches, batch ids that matched nothing)."""
    sql = au.load_sql(
        "batch_id_name.sql",
        {"database": database, "batch_filter": build_filter(batch_ids)},
    )
    output_location = au.run_query(session, sql, database)
    rows = au.fetch_result_rows(session, output_location)
    next(rows, None)  # drop the header row Athena always emits

    matches = [BatchMatch(name=row[1], contract_count=row[0]) for row in rows if row]
    missing = [b for b in batch_ids if not any(b in m.name for m in matches)]
    return matches, missing


def print_matches(matches: Sequence[BatchMatch], missing: Sequence[str]) -> None:
    """Print the resolved batches as a table, then anything that was not found."""
    if matches:
        width = max(len(m.name) for m in matches)
        print()
        print(f"  {'batch':<{width}}  contract_id_count")
        print(f"  {'-' * width}  -----------------")
        for match in matches:
            print(f"  {match.name:<{width}}  {match.contract_count:>17}")

    for batch_id in missing:
        print(f"[warn]   no batch matching {batch_id!r}", file=sys.stderr)


def confirm(question: str, assume_yes: bool = False) -> bool:
    """Ask the terminal to confirm. Never blocks when stdin is not a terminal."""
    if assume_yes:
        print(f"{question} [y/N]: y   (--yes)")
        return True

    if not sys.stdin.isatty():
        raise ValueError(
            "need to confirm the batches but stdin is not a terminal; "
            "re-run with --yes to skip the prompt"
        )

    try:
        answer = input(f"{question} [y/N]: ").strip().lower()
    except EOFError:
        return False
    return answer in ("y", "yes")
