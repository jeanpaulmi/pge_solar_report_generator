"""Shared helpers for the PG&E solar report scripts.

Handles SQL template loading, Athena query execution, downloading the result
set, and publishing the cleaned output to S3 + the local ``output/`` folder.
"""

from __future__ import annotations

import csv
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator, Sequence

import boto3
from botocore.exceptions import BotoCoreError, ClientError, ProfileNotFound

from config import REPO_ROOT, get_settings

SQL_DIR = REPO_ROOT / "sql"
OUTPUT_DIR = REPO_ROOT / "output"

VALID_DATABASES = ("pge", "pge_stage", "pge_uat")
POLL_TIMEOUT_SECONDS = 1800  # 30 minutes
SSO_LOGIN_TIMEOUT_SECONDS = 300  # time allowed to approve the login in the browser


class AthenaQueryError(RuntimeError):
    """Raised when an Athena query does not reach SUCCEEDED."""


# --------------------------------------------------------------------------
# dates
# --------------------------------------------------------------------------
def report_year(now: datetime | None = None) -> int:
    """The year the report covers: always the calendar year before this one."""
    return (now or datetime.now()).year - 1


def run_stamp(now: datetime | None = None) -> str:
    """Timestamp used in the run folder name."""
    return (now or datetime.now()).strftime("%Y%m%d_%H%M%S")


# --------------------------------------------------------------------------
# sql templating
# --------------------------------------------------------------------------
def load_sql(filename: str, variables: dict[str, str]) -> str:
    """Read ``sql/<filename>`` and substitute every ``{{name}}`` placeholder."""
    path = SQL_DIR / filename
    sql = path.read_text()

    for name, value in variables.items():
        sql = sql.replace("{{" + name + "}}", str(value))

    leftover = re.findall(r"\{\{(\w+)\}\}", sql)
    if leftover:
        raise ValueError(
            f"{path.name}: unsubstituted placeholders {sorted(set(leftover))}"
        )

    # Athena runs a single statement; a trailing semicolon is not needed.
    return sql.strip().rstrip(";").strip()


def quoted_sql_list(values: Iterable[str]) -> str:
    """Render values as a quoted, comma-separated SQL IN-list."""
    items = [str(v).strip() for v in values if str(v).strip()]
    if not items:
        raise ValueError("expected at least one value for the SQL IN-list")
    for item in items:
        if "'" in item:
            raise ValueError(f"value contains a single quote and cannot be used: {item!r}")
    return ",\n      ".join(f"'{item}'" for item in items)


def validate_database(database: str) -> str:
    db = database.strip()
    if not re.fullmatch(r"[A-Za-z0-9_]+", db):
        raise ValueError(f"invalid database name: {database!r}")
    if db not in VALID_DATABASES:
        print(
            f"[warn] database {db!r} is not one of {VALID_DATABASES}; continuing anyway",
            file=sys.stderr,
        )
    return db


# --------------------------------------------------------------------------
# aws
# --------------------------------------------------------------------------
# Credential problems that a fresh `aws sso login` can plausibly fix. Anything
# else (e.g. AccessDenied on a real call) is a permissions issue, not a stale
# token, and must not trigger a login attempt.
_RETRYABLE_AUTH_ERRORS = (
    "SSOError",
    "SSOTokenLoadError",
    "UnauthorizedSSOTokenError",
    "TokenRetrievalError",
    "NoCredentialsError",
    "CredentialRetrievalError",
    "UnknownTokenProviderError",
)
_RETRYABLE_AUTH_CODES = (
    "ExpiredToken",
    "ExpiredTokenException",
    "InvalidClientTokenId",
    "UnrecognizedClientException",
)


def _build_session() -> boto3.Session:
    settings = get_settings()
    profile = (settings.AWS_PROFILE or "").strip()
    region = settings.ATHENA_REGION

    if profile:
        try:
            return boto3.Session(profile_name=profile, region_name=region)
        except ProfileNotFound:
            print(
                f"[warn] AWS profile {profile!r} not found; falling back to default credentials",
                file=sys.stderr,
            )
    return boto3.Session(region_name=region)


def _whoami(session: boto3.Session) -> str:
    """Force credential resolution. Raises if the session cannot authenticate."""
    identity = session.client("sts").get_caller_identity()
    return f"{identity['Account']} / {identity['Arn'].rsplit('/', 1)[-1]}"


def _is_expired_credentials(exc: Exception) -> bool:
    if type(exc).__name__ in _RETRYABLE_AUTH_ERRORS:
        return True
    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "")
        if code in _RETRYABLE_AUTH_CODES:
            return True
    # Some botocore versions surface an expired SSO token as a generic error.
    message = str(exc).lower()
    return "token has expired" in message or "sso session associated" in message


def sso_login() -> None:
    """Shell out to `aws sso login` for the configured profile."""
    profile = (get_settings().AWS_PROFILE or "").strip()
    if not profile:
        raise AthenaQueryError(
            "AWS credentials are missing or expired and no AWS_PROFILE is configured "
            "in .env, so an SSO login cannot be started automatically."
        )

    aws_bin = shutil.which("aws")
    if not aws_bin:
        raise AthenaQueryError(
            "AWS credentials are expired and the aws CLI is not on PATH.\n"
            f"        run this yourself, then re-run: aws sso login --profile {profile}"
        )

    print(f"[aws]    credentials expired -> aws sso login --profile {profile}")
    print("[aws]    approve the request in the browser window that opens ...")
    try:
        result = subprocess.run(
            [aws_bin, "sso", "login", "--profile", profile],
            timeout=SSO_LOGIN_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise AthenaQueryError(
            f"aws sso login was not completed within {SSO_LOGIN_TIMEOUT_SECONDS}s"
        ) from None

    if result.returncode != 0:
        raise AthenaQueryError(f"aws sso login failed (exit code {result.returncode})")


def aws_session(auto_login: bool = True) -> boto3.Session:
    """Return an authenticated session, refreshing an expired SSO token if needed."""
    session = _build_session()

    try:
        print(f"[aws]    authenticated as {_whoami(session)}")
        return session
    except Exception as exc:  # noqa: BLE001 - re-raised below unless recoverable
        if not (auto_login and _is_expired_credentials(exc)):
            raise AthenaQueryError(_credential_hint(exc)) from exc

    sso_login()

    # Rebuild the session so botocore re-reads the refreshed token cache.
    session = _build_session()
    try:
        print(f"[aws]    authenticated as {_whoami(session)}")
    except Exception as exc:  # noqa: BLE001
        raise AthenaQueryError(_credential_hint(exc)) from exc

    return session


def _split_s3_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("s3://"):
        raise ValueError(f"not an s3 uri: {uri}")
    bucket, _, key = uri[len("s3://") :].partition("/")
    return bucket, key


def validate_s3_config() -> None:
    """Fail fast on a staging location we will not be able to read back.

    Athena writes results to ATHENA_S3_STAGING_DIR and we then download them.
    REPORT_S3_BUCKET is the publish target and is write-only under the current
    account policy (it denies s3:GetObject), so the two must never be the same
    bucket -- otherwise the query runs and bills us before failing on download.
    """
    settings = get_settings()
    staging = settings.ATHENA_S3_STAGING_DIR.strip()

    if not staging.startswith("s3://"):
        raise AthenaQueryError(
            f"ATHENA_S3_STAGING_DIR must be an s3:// uri, got {staging!r} (check .env)"
        )

    staging_bucket, _ = _split_s3_uri(staging)
    if staging_bucket == settings.REPORT_S3_BUCKET:
        raise AthenaQueryError(
            f"ATHENA_S3_STAGING_DIR is in {staging_bucket!r}, which is also "
            f"REPORT_S3_BUCKET (the publish target).\n"
            f"        That bucket is write-only -- it denies s3:GetObject -- so Athena "
            f"results written there cannot be read back.\n"
            f"        Point ATHENA_S3_STAGING_DIR in .env at the Athena results bucket, "
            f"e.g. s3://aws-athena-query-results-<account>-<region>/<you>/"
        )


def run_query(session: boto3.Session, sql: str, database: str) -> str:
    """Run ``sql`` against ``database`` and return the S3 uri of the result CSV."""
    settings = get_settings()
    validate_s3_config()
    athena = session.client("athena")

    print(f"[athena] submitting query against {database} ...")
    try:
        query_id = athena.start_query_execution(
            QueryString=sql,
            QueryExecutionContext={"Database": database},
            ResultConfiguration={"OutputLocation": settings.ATHENA_S3_STAGING_DIR},
            WorkGroup=settings.ATHENA_WORKGROUP,
        )["QueryExecutionId"]
    except (ClientError, BotoCoreError) as exc:
        raise AthenaQueryError(_credential_hint(exc)) from exc

    print(f"[athena] query id {query_id}")

    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    delay = 1.0
    while True:
        execution = athena.get_query_execution(QueryExecutionId=query_id)["QueryExecution"]
        state = execution["Status"]["State"]

        if state == "SUCCEEDED":
            break
        if state in ("FAILED", "CANCELLED"):
            reason = execution["Status"].get("StateChangeReason", "no reason reported")
            raise AthenaQueryError(f"query {query_id} {state}: {reason}")
        if time.monotonic() > deadline:
            athena.stop_query_execution(QueryExecutionId=query_id)
            raise AthenaQueryError(
                f"query {query_id} exceeded {POLL_TIMEOUT_SECONDS}s and was cancelled"
            )

        time.sleep(delay)
        delay = min(delay * 1.5, 10.0)

    stats = execution.get("Statistics", {})
    scanned_mb = stats.get("DataScannedInBytes", 0) / (1024 * 1024)
    runtime_s = stats.get("TotalExecutionTimeInMillis", 0) / 1000
    print(f"[athena] succeeded in {runtime_s:.1f}s, scanned {scanned_mb:.1f} MB")

    return execution["ResultConfiguration"]["OutputLocation"]


def fetch_result_rows(session: boto3.Session, output_location: str) -> Iterator[list[str]]:
    """Yield rows (including the header row) from the Athena result CSV."""
    bucket, key = _split_s3_uri(output_location)
    s3 = session.client("s3")

    handle, tmp_path = tempfile.mkstemp(prefix="athena_result_", suffix=".csv")
    os.close(handle)
    try:
        try:
            s3.download_file(bucket, key, tmp_path)
        except ClientError as exc:
            raise AthenaQueryError(
                f"could not read Athena results from {output_location}: {exc}\n"
                f"        gridx-temp denies s3:GetObject; ATHENA_S3_STAGING_DIR in .env must "
                f"point at a readable bucket, e.g. "
                f"s3://aws-athena-query-results-743512984079-us-west-2/<you>/"
            ) from exc
        with open(tmp_path, newline="", encoding="utf-8") as fh:
            yield from csv.reader(fh)
    finally:
        os.unlink(tmp_path)


def upload_file(session: boto3.Session, local_path: Path, s3_uri: str) -> None:
    bucket, key = _split_s3_uri(s3_uri)
    session.client("s3").upload_file(str(local_path), bucket, key)
    print(f"[s3]     uploaded -> {s3_uri}")


# --------------------------------------------------------------------------
# output writing
# --------------------------------------------------------------------------
def write_delimited(
    path: Path,
    rows: Iterable[Sequence[str]],
    delimiter: str = ",",
    header: Sequence[str] | None = None,
) -> int:
    """Write rows without any quoting. Returns the number of data rows written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    written = 0

    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        if header is not None:
            fh.write(delimiter.join(_clean(f, delimiter) for f in header) + "\n")
        for row in rows:
            fh.write(delimiter.join(_clean(f, delimiter) for f in row) + "\n")
            written += 1

    print(f"[local]  wrote {written} rows -> {path}")
    return written


def split_evenly(items: Sequence[str], parts: int) -> list[Sequence[str]]:
    """Split ``items`` into ``parts`` chunks of as near-equal size as possible.

    Any remainder goes to the earliest chunks, so 101 items over 2 parts gives
    51 and 50, and 100 over 3 gives 34, 33, 33.
    """
    if parts < 1:
        raise ValueError(f"parts must be >= 1, got {parts}")

    base, extra = divmod(len(items), parts)
    chunks: list[Sequence[str]] = []
    start = 0
    for i in range(parts):
        size = base + (1 if i < extra else 0)
        chunks.append(items[start : start + size])
        start += size
    return chunks


def part_label(index: int, total: int) -> str:
    """1-based part label, zero padded to the width of ``total``.

    2 parts -> part1of2, part2of2;  12 parts -> part01of12 ... part12of12,
    so the filenames sort in numeric order.
    """
    return f"part{index:0{len(str(total))}d}of{total}"


_DELIMITER_ALIASES = {
    "tab": "\t",
    "\\t": "\t",
    "comma": ",",
    "pipe": "|",
    "semicolon": ";",
    "space": " ",
}


def resolve_delimiter(value: str) -> str:
    """Turn a shell-friendly delimiter spec into a single character.

    Accepts a literal character (including an actual tab), a name such as
    ``tab`` or ``pipe``, or an escape sequence such as ``\\t``. Shell variables
    cannot easily carry a raw tab, so the name form is the usual way to ask for
    one from the .sh wrapper.
    """
    if len(value) == 1:
        return value

    alias = _DELIMITER_ALIASES.get(value.strip().lower())
    if alias:
        return alias

    decoded = value.encode("utf-8").decode("unicode_escape")
    if len(decoded) != 1:
        raise ValueError(
            f"delimiter must resolve to a single character, got {value!r} "
            f"(try: tab, comma, pipe, semicolon)"
        )
    return decoded


def _clean(field: str, delimiter: str) -> str:
    """Strip quoting/newlines so no field is ever wrapped in quotes."""
    value = "" if field is None else str(field)
    value = value.replace("\r", " ").replace("\n", " ").strip()
    if delimiter in value:
        print(
            f"[warn] value {value!r} contains the {delimiter!r} delimiter; replaced with a space",
            file=sys.stderr,
        )
        value = value.replace(delimiter, " ")
    return value


def _credential_hint(exc: Exception) -> str:
    settings = get_settings()
    return (
        f"AWS call failed: {exc}\n"
        f"        if this looks like a credentials problem, log in manually and retry:\n"
        f"        aws sso login --profile {settings.AWS_PROFILE}"
    )
