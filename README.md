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
(`pge_stage` | `pge_uat` | `pge`), optional `REPORT_YEAR`.

`contract_start_date >= <report year>-01-01`, where the report year auto-derives as
**current calendar year − 1** (run in 2026 → 2025). Set `REPORT_YEAR` to override.

Output — one contract id per line, **no header, no quotes**:

```
output/contract_ids_<YYYYMMDD_HHMMSS>/contract_ids_<YYYYMMDD_HHMMSS>.csv
s3://gridx-temp/jpm/pge_solar_report/contract_ids_<YYYYMMDD_HHMMSS>/...
```

## Step 2 — seasonal county report

```bash
./run_seasonal_report.sh
```

Runs [sql/seasonal_county_stats.sql](sql/seasonal_county_stats.sql). Config:
`DATABASE`, `SEASON` (`Spring` | `Summer` | `Fall` | `Winter` | `All`), `BATCH_IDS`
(bash array — add/remove lines freely), optional `BILL_YEARS`, `DELIMITER`,
`NO_HEADER`, `FILE_DATE_FORMAT`.

`billyear IN (...)` auto-derives as **(current year − 1, current year)**. Set
`BILL_YEARS="2024,2025"` to override.

`DELIMITER` defaults to `tab`. It also accepts `comma`, `pipe`, `semicolon`, an
escape such as `\t`, or a literal character — the names exist because a shell
variable cannot easily carry a raw tab.

Output — **tab separated**, **no quotes on any value**. `AVG_SOLARCHRG_RANGE` is
formatted to exactly 2 decimal places; `AVG_SAVINGS_RANGE` is whole percentages:

```
output/<season>_report_<YYYYMMDD_HHMMSS>/SBP_Suplemental_<YYYYMMDD>.txt
s3://gridx-temp/jpm/pge_solar_report/<season>_report_<YYYYMMDD_HHMMSS>/...
```

```
PREMISE_COUNTY	AVG_SOLARCHRG_RANGE	AVG_SAVINGS_RANGE	SEASON	CUSTOMER_COUNT
Fresno	$77.18 - $111.07	64% - 88%	Fall	8062
Contra Costa	$71.92 - $109.50	56% - 82%	Fall	7302
```

## Useful flags

Both wrappers forward extra flags to the Python script:

```bash
./run_seasonal_report.sh --print-sql
```

- `--print-sql` — render the SQL with all substitutions and exit (no query run)
- `--no-upload` — write the local copy only, skip S3 (also `SKIP_UPLOAD="true"`)
- `--no-auto-login` — fail on expired credentials instead of opening an SSO login

## Layout

| Path | Purpose |
| --- | --- |
| `run_contract_ids.sh` / `run_seasonal_report.sh` | config + entry points |
| `get_contract_ids.py` / `generate_seasonal_report.py` | step logic |
| `athena_utils.py` | SQL templating, query execution, output writing, S3 upload |
| `sql/` | the two queries, with `{{name}}` placeholders |
| `output/` | local copies of every run |
