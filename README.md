# PG&E Solar Report Generator

Two Athena-backed steps. Each has a `.sh` wrapper holding all the knobs — edit the
CONFIG block at the top of the script and run it. Nothing else needs editing.

## Setup (macOS)

### Prerequisites

| Need | Check | Install |
| --- | --- | --- |
| Python 3.14.0 | `python3 --version` | `pyenv install 3.14.0` (see below) |
| AWS CLI v2 | `aws --version` | `brew install awscli` |
| AWS SSO access | `aws configure list-profiles` | see *AWS profile* below |

Python version is pinned in `.python-version`. If you use
[pyenv](https://github.com/pyenv/pyenv) (`brew install pyenv`), it picks the right
one up automatically inside this folder:

```bash
pyenv install 3.14.0
```

Any Python 3.11+ works — nothing here depends on 3.14 specifically — but the pinned
version is what the lockfile in `requirements.txt` was resolved against.

### Create the venv

From the repo root:

```bash
python3 -m venv venv
```

```bash
./venv/bin/python -m pip install --upgrade pip
```

```bash
./venv/bin/pip install -r requirements.txt
```

Activating the venv is optional — both `.sh` wrappers call `./venv/bin/python`
directly, falling back to `python3` if no venv exists. To activate it anyway for
interactive work:

```bash
source venv/bin/activate
```

### AWS profile

The scripts use the `AWS_PROFILE` named in `.env`
(`743512984079_customer-success`). It must already exist in `~/.aws/config` as an
SSO profile:

```ini
[profile 743512984079_customer-success]
sso_session = awslogin
sso_account_id = 743512984079
sso_role_name = customer-success
region = us-west-2

[sso-session awslogin]
sso_start_url = https://identitycenter.amazonaws.com/ssoins-7907996d1d1cc210
sso_region = us-west-2
sso_registration_scopes = sso:account:access
```

You need read access to the `pge*` Athena databases, read/write on
`s3://aws-athena-query-results-743512984079-us-west-2/` (Athena results), and
write on `s3://gridx-temp/jpm/` (published output). `gridx-temp` denies
`s3:GetObject`, so it cannot be used as `ATHENA_S3_STAGING_DIR` — the scripts check
this at startup and refuse to run before submitting a query, rather than failing
after you have already paid for the scan. No need to log in first — see
*Credentials* below.

### Environment file

```bash
cp .env.example .env
```

That is enough to run both scripts as-is — every key they use (`AWS_PROFILE`,
`ATHENA_*`, `REPORT_S3_*`) is already filled in. The blank `DB_*` /
`PRICING_ENGINE_*` entries are MySQL settings inherited from the wider skeleton;
`config.py` requires the keys to exist but neither script reads them, so empty
values are fine. Fill them in only if you add MySQL work to this repo.

### Verify

Renders the SQL without touching AWS:

```bash
./run_contract_ids.sh --print-sql
```

## Credentials

Nothing to do up front. Both scripts check the AWS session before querying, and if
the SSO token has expired they run `aws sso login --profile <AWS_PROFILE>` for you
and continue once you approve it in the browser:

```
[aws]    credentials expired -> aws sso login --profile 743512984079_customer-success
[aws]    approve the request in the browser window that opens ...
[aws]    authenticated as 743512984079 / you@gridx.com
```

The login is only attempted for genuine credential failures (expired/missing SSO
token). A permissions error such as `AccessDenied` fails immediately instead of
looping through a pointless login. Pass `--no-auto-login` to disable the behaviour
entirely — worth doing for unattended/cron runs, where the browser prompt would
just hang until it times out (5 minutes).

## Configuration

All AWS/Athena settings and the report output location live in `.env`; `config.py`
only declares them, with no hardcoded fallbacks — a missing key fails immediately
with a clear validation error rather than silently using a stale default.

| Key | Purpose |
| --- | --- |
| `AWS_PROFILE` | profile used for the session and for `aws sso login` |
| `ATHENA_REGION`, `ATHENA_WORKGROUP` | where queries run |
| `ATHENA_S3_STAGING_DIR` | Athena's raw result location |
| `ATHENA_DATABASE` | fallback only; both scripts pass `--database` explicitly |
| `REPORT_S3_BUCKET`, `REPORT_S3_PREFIX` | published output root |

`.env` is gitignored. `.env.example` is tracked and lists every required key with
the non-secret values filled in — copy it to `.env` and add the passwords.

## Step 1 — contract ids

```bash
./run_contract_ids.sh
```

Runs [sql/contract_ids.sql](sql/contract_ids.sql). Config: `DATABASE`
(`pge_stage` | `pge_uat` | `pge`), `PARTITIONS`, optional `REPORT_YEAR`.

`REPORT_YEAR` auto-derives as **current calendar year − 1** (run in 2026 → 2025).
Note that the `contract_start_date` and `service_status` filters are currently
commented out in the SQL, so `REPORT_YEAR` has no effect until they are restored.

Output — one contract id per line, **no header, no quotes**:

```
output/contract_ids_<YYYYMMDD_HHMMSS>/contract_ids_<YYYYMMDD_HHMMSS>.csv
s3://gridx-temp/jpm/pge_solar_report/contract_ids_<YYYYMMDD_HHMMSS>/...
```

### Splitting across multiple files

Large pulls can be split with `PARTITIONS` in the wrapper (or `--partitions N`).
`PARTITIONS="1"` is the default and writes the single file named above.

With `N > 1` the ids are divided into `N` near-equal files in the same run folder,
each one still headerless and unquoted. Any remainder goes to the earliest files,
so 101 ids over 2 partitions gives 51 + 50:

```
contract_ids_<YYYYMMDD_HHMMSS>_part1of3.csv
contract_ids_<YYYYMMDD_HHMMSS>_part2of3.csv
contract_ids_<YYYYMMDD_HHMMSS>_part3of3.csv
```

Part numbers are zero padded to the width of `N` (`part01of12` … `part12of12`) so
the files sort in order. Concatenating the parts reproduces the single-file output
exactly — no id is dropped, duplicated, or reordered. Every part is uploaded to the
same S3 run folder.

If `PARTITIONS` exceeds the number of ids returned, the script warns and writes one
file per id rather than leaving empty files behind. A query returning no rows always
writes a single empty file.

## Step 2 — seasonal county report

```bash
./run_seasonal_report.sh
```

Runs [sql/seasonal_county_stats.sql](sql/seasonal_county_stats.sql). Config:
`DATABASE`, `SEASON` (`Spring` | `Summer` | `Fall` | `Winter` | `All`), `BATCH_IDS`
(bash array — add/remove lines freely), `AUTO_CONFIRM`, optional `BILL_YEARS`,
`DELIMITER`, `NO_HEADER`, `FILE_DATE_FORMAT`.

`billyear IN (...)` auto-derives as the **report year (current year − 1)**. Set
`BILL_YEARS="2024"` to override.

### Batch ids are looked up for you

`BATCH_IDS` takes short batch **numbers** — no need to paste full batch names:

```bash
BATCH_IDS=(
  "252882"
  "252883"
)
```

Before running the report, every entry is looked up in `accountbillinglog` (one
query covering all of them), listed with its contract count, and confirmed at the
terminal:

```
[batch]  looking up 2 batch id(s) in accountbillinglog ...

  batch                                   contract_id_count
  --------------------------------------  -----------------
  azkaban_PGE_pge_on_demand_batch_252882             152267
  azkaban_PGE_pge_on_demand_batch_252883              11127

Run the Winter report on 2 batch(es)? [y/N]:
```

Answering anything other than `y`/`yes` cancels without writing a report (exit 1).
This replaces the old two-step flow of running `run_batch_id_name.sh` first and
pasting the names across — that script still exists if you just want to check
whether a batch was created, but the report no longer needs it.

Full batch names still work and are verified the same way, since the lookup
matches on a substring.

- A batch number that matches **nothing** is reported as `[warn] no batch matching
  '...'` and the prompt says how many are being ignored, so you can abort.
- If **none** of the ids match, the report errors out instead of prompting.
- If one number matches **several** batches, all of them are listed and included —
  the prompt is where you catch that.
- `AUTO_CONFIRM="true"` (or `--yes`) skips the prompt. Required for unattended
  runs: with no terminal to answer, the script errors out rather than hanging.
- `--no-resolve` uses the `BATCH_IDS` values verbatim, with no lookup and no
  prompt.

`DELIMITER` defaults to `tab`. It also accepts `comma`, `pipe`, `semicolon`, an
escape such as `\t`, or a literal character — the names exist because a shell
variable cannot easily carry a raw tab.

Output — **tab separated**, **no quotes on any value**. `AVG_SOLARCHRG_RANGE` is
rounded to whole dollars and `AVG_SAVINGS_RANGE` to whole percentages:

```
output/<season>_report_<YYYYMMDD_HHMMSS>/SBP_Supplemental_<YYYYMMDD>.txt
s3://gridx-temp/jpm/pge_solar_report/<season>_report_<YYYYMMDD_HHMMSS>/...
```

```
PREMISE_COUNTY	AVG_SOLARCHRG_RANGE	AVG_SAVINGS_RANGE	SEASON	CUSTOMER_COUNT
Fresno	$29 - $43	53% - 69%	Winter	704
Santa Clara	$30 - $45	40% - 60%	Winter	647
```

## Useful flags

Both wrappers forward extra flags to the Python script:

```bash
./run_seasonal_report.sh --print-sql
```

- `--print-sql` — render the SQL with all substitutions and exit. For the seasonal
  report this still runs the batch lookup (the resolved names go into the SQL), but
  that output goes to stderr so stdout stays pipeable. Add `--no-resolve` to skip
  the lookup and render offline.
- `--no-upload` — write the local copy only, skip S3 (also `SKIP_UPLOAD="true"`)
- `--no-auto-login` — fail on expired credentials instead of opening an SSO login
- `--partitions N` — step 1 only: split the ids across N files (also `PARTITIONS`)
- `--yes` — step 2 only: skip the batch confirmation (also `AUTO_CONFIRM="true"`)
- `--no-resolve` — step 2 only: use `BATCH_IDS` verbatim, no lookup, no prompt

## Layout

| Path | Purpose |
| --- | --- |
| `run_contract_ids.sh` / `run_seasonal_report.sh` | config + entry points |
| `get_contract_ids.py` / `generate_seasonal_report.py` | step logic |
| `athena_utils.py` | SQL templating, query execution, output writing, S3 upload |
| `batch_lookup.py` | batch number → batch name lookup, table, confirm prompt |
| `run_batch_id_name.sh` / `batch_id_name.py` | optional standalone batch check |
| `sql/` | the queries, with `{{name}}` placeholders |
| `output/` | local copies of every run |
