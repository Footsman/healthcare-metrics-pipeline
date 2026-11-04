# Healthcare Metrics Pipeline

An end-to-end data pipeline over CMS Payroll-Based Journal (PBJ) nurse staffing data. It pulls source files from Google Drive, builds a medallion lake on S3, computes five facility-level staffing metrics, validates them against CMS's own published figures, and serves them through Athena and a Streamlit dashboard. It runs weekly on AWS with no human involvement.

Built for the DE Academy end-to-end project.

---

## The question

Regional managers overseeing a portfolio of nursing homes need to know which facilities are staffed out of line with the residents they care for, and whether thin staffing coincides with worse patient outcomes. Answering that today means assembling three separate CMS datasets by hand.

## The data

| Source | Grain | Rows |
|---|---|---|
| `PBJ_Daily_Nurse_Staffing_Q2_2024.csv` | One row per facility per day | 1,325,324 |
| `NH_ProviderInfo_Oct2024.csv` | One row per facility | 14,814 |
| `NH_QualityMsr_Claims_Oct2024.csv` | One row per facility per measure | 59,256 |

Q2 2024, 1 April to 30 June: 14,564 facilities reporting all 91 days, with no gaps, no nulls, and no duplicate `(PROVNUM, WorkDate)` pairs. Three of 21 available CMS files are ingested; the other 18 are excluded deliberately, since each one costs grain analysis, period reconciliation, join validation and suppression handling, and none of them changes an answer.

Two properties of the source constrain the design rather than merely annoying it. The master file is Windows-1252, not UTF-8, so normalisation is a hard prerequisite of bronze. `PROVNUM` carries significant leading zeros, so it is read and stored as a string throughout — read as an integer, the facility join silently collapses.

## Architecture

```
Google Drive  (21 files, 3 in scope)
      │
      │  md5Checksum compared against a DynamoDB watermark
      ▼
  Lambda  pbj-ingest ─────────────────────►  s3://…/lake/raw/
      │                                            │
      │  returns {pulled: [...], skipped: [...]}    │  original bytes, never parsed
      ▼                                            ▼
  Step Functions choice ── nothing new ──► end   Glue  pbj-bronze
      │                                            │  CSV → Parquet, cp1252 → UTF-8,
      │                                            │  Drive provenance columns
      │                                            ▼
      │                                          lake/bronze/
      │                                            │
      │                                          Glue  pbj-silver
      │                                            │  typed, facility-day grain
      │                                            ▼
      │                                          lake/silver/
      │                                            │
      │                                          Glue  pbj-gold
      │                                            │  five metrics + CMS validation gate
      ▼                                            ▼
  EventBridge Scheduler                         lake/gold/
  (Mondays 08:00 PT)                               │
                                 ┌─────────────────┴─────────────────┐
                                 ▼                                   ▼
                      Glue Catalog + Athena                Streamlit on ECS Express Mode
```

Everything is in `us-east-1`. The pipeline is a four-state Step Functions machine: ingest, a choice, then three Glue jobs chained with `startJobRun.sync`.

**Why Lambda for ingest and Glue for transforms.** The Lambda writes raw bytes only, which keeps pandas and pyarrow out of its deployment package. That matters because packages with compiled extensions must be built for Linux — a wheel installed on Windows will not load in Lambda's runtime, and the zip is capped at 250 MB unzipped. A Glue Python Shell job reads its script from S3 and pip-installs pinned versions at start, so there is no packaging step at all.

**Why the pipeline sometimes does nothing.** If every checksum matches, nothing downstream has changed. The choice state ends the run without starting three Glue jobs, so a weekly check that finds nothing costs one Lambda invocation and three DynamoDB reads.

**Why retries are safe.** Every write is a partition overwrite on a deterministic key, never an append. Idempotency is what buys the automatic retry policy; without it a half-failed job could not be re-run blindly.

**Why the watermark is written last.** It is recorded only after the S3 write succeeds. Record it first and a failed upload is marked ingested, so the next run skips it forever.

## Validation

`build_gold.py` will not write a partition unless its own HPRD reproduces the figure CMS publishes per facility:

```
OK   CMS HPRD mean abs difference      0.00003 <=  0.00100
OK   CMS HPRD p99.9 abs difference     0.00001 <=  0.01000
OK   CMS HPRD facilities over tol      1.00000 <=  5.00000
     validated against 14,415 facilities with a published CMS figure
```

Four candidate HPRD definitions were tested against CMS. The one including administrative and specialty nursing categories reproduces the published figure exactly; the metric this pipeline reports counts direct care only and is therefore about 0.39 lower, deliberately.

The gate is a max-tolerant mean rather than a hard maximum, because one facility closing mid-quarter legitimately disagrees and should not fail an otherwise correct build.

## Findings

**Facilities staff to resident count, not to how full the building is.** Total direct-care hours track resident-days at r = 0.93, while hours per resident day is nearly flat across occupancy deciles — 3.25 at 47% full against 3.38 at 97%. The headline "HPRD vs occupancy, r = 0.017" is a measurement artifact: HPRD divides by census and occupancy multiplies by it, so the two share a term before any real relationship exists.

**Contract staffing is 7.7% nationally, not 0.70%.** The median facility uses almost no agency staff; a minority rely on it heavily. The national figure is hours-weighted, which is why gold stores direct-care hours and contract hours as separate additive measures rather than storing the ratio. Ratios do not roll up.

**93 facilities report near-zero hours.** That is a reporting failure, not a staffing level, and they would top any "lowest staffing" ranking. They are flagged with `reporting_complete`, not dropped; the dashboard excludes them by default behind a toggle.

**6.4% of facility-days report zero RN hours**, against a federal expectation of RN coverage eight hours a day, seven days a week.

## Repo layout

```
src/
  ingest_drive.py     Local: Google Drive → bronze, checksum watermark in a JSON file
  build_bronze.py     Local: CSV → Parquet
  build_silver.py     Local: typed tables at a declared grain, with grain checks
  build_gold.py       Local: five metrics, CMS validation gate
  app.py              Streamlit dashboard, four tabs
  Dockerfile          Container for the dashboard

  lambda_ingest.py    Deployed: the ingest Lambda
  glue_bronze.py      Deployed: bronze Glue job
  glue_silver.py      Deployed: silver Glue job
  glue_gold.py        Deployed: gold Glue job

  profile_pbj.py      Exploration: profiling and distribution checks
  grain_check.py      Exploration: proving the grain
  find_cases.py       Exploration: chasing specific facilities

infra/                IAM trust and permission policies, Glue job definitions,
                      the Step Functions state machine
```

The `build_*.py` and `glue_*.py` pairs are the same transforms with different I/O. The local versions read and write a `lake/` folder; the deployed versions read and write S3 and take their configuration from Glue job parameters. Everything between the I/O helpers is identical.

## Running it locally

Requires Python 3.11+ and the three CSVs in `lake/raw/`.

```bash
pip install pandas pyarrow streamlit plotly boto3 google-api-python-client google-auth

python src/build_bronze.py
python src/build_silver.py
python src/build_gold.py
streamlit run src/app.py
```

To pull from Google Drive instead of using local files, put a service account key at `../secrets/pbj-ingest-key.json` and run `python src/ingest_drive.py` first. That path sits outside this repository on purpose.

## Deploying

Infrastructure is created with the AWS CLI from the JSON definitions in `infra/`. Deploying new code is:

```bash
# Glue jobs: the job reads its script from S3 on every run
aws s3 cp src/glue_gold.py s3://BUCKET/scripts/glue_gold.py

# Lambda: rebuild the zip with Linux wheels, then update
pip install --target build --platform manylinux2014_x86_64 --implementation cp \
    --python-version 3.13 --only-binary=:all: google-api-python-client google-auth
cp src/lambda_ingest.py build/
python -c "import shutil; shutil.make_archive('lambda_ingest','zip','build')"
aws lambda update-function-code --function-name pbj-ingest --zip-file fileb://lambda_ingest.zip
```

The dashboard is built and pushed to ECR, then run as an ECS Express Mode service. It is created for a demonstration and deleted afterwards — it is the only component that bills continuously, at roughly $36/month if left running against under $1 for the entire pipeline.

## Limitations

**The outcome measure precedes the staffing window.** Readmission covers April 2023 to March 2024; staffing covers April to June 2024. Any relationship reported is a cross-sectional association, not a causal one, and it assumes facility staffing is stable across adjacent quarters.

**Denominators do not match.** HPRD is computed over `MDScensus`, which counts all residents. CMS measure 521 covers short-stay residents only.

**Suppression is not random.** Roughly 2,900 facilities carry no reportable readmission score, the large majority under CMS footnote 9 — too few qualifying stays to report reliably. That correlates with facility size, so correlation results describe mid-size and large facilities rather than the full population.

**Two files will drift.** `SOURCES` and `FIELDS` are duplicated between `ingest_drive.py` and `lambda_ingest.py`. The fix is a shared `config.py` both import.

## Not calculable from this data

The brief asks for overtime percentage, shifts per nurse, length of stay, and time-of-day shift utilisation. None are derivable: PBJ carries no nurse identifiers, no shift times, no wages, and no admission or discharge dates. Two of the four required questions are reframed rather than silently substituted — the reasoning is in the solution design document.