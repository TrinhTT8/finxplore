# FinXplore

**Understand any S&P 500 company's financials in plain English.**

FinXplore turns SEC filing data into beginner-friendly charts, sector context and a guarded AI
analyst. You don't need a finance background to use it. It runs serverless on AWS for about $0–5 a month.

> For education only, not investment advice.

## Features (MVP)

- **Company pages:** 10+ years of ~15 core metrics, each with a plain-English label and a hover tooltip.
- **Sector context:** "Profit margin is higher than most Tech companies" (compared with the sector median).
- **Compare:** up to 4 companies on one metric, with a plain-English takeaway.
- **AI snapshot and "Explain this":** short, grounded explanations written for beginners.
- **AI analyst:** a question becomes validated, read-only SQL, and the answer comes back as a table, a plain explanation and the SQL that was run.
- **Nightly refresh** from SEC EDGAR, with monitoring and alerts.

## Architecture

```
Browser ─▶ CloudFront ─▶ S3 (React app)
   │
   └──▶ API Gateway (HTTP API, Cognito JWT on /ai/*) ─▶ API Lambda
                                                        ├─▶ DynamoDB (cache, quotas)
                                                        ├─▶ Athena ─▶ S3 data lake (Parquet)
                                                        └─▶ Bedrock (text → SQL → sqlglot validator)

EventBridge (nightly) ─▶ Step Functions ─▶ SQS ─▶ worker Lambda ─▶ SEC EDGAR ─▶ S3 raw/ + curated/
```

The S3 data lake is the single source of truth. The nightly pipeline writes to it, and the
website and AI analyst read from it through Athena. There is no database server to run.

## Design overview

### Data pipeline

1. **EventBridge Scheduler** starts a **Step Functions** workflow every night.
2. A plan step reads the S&P 500 company list and sends one **SQS** message per company (~500).
3. A **worker Lambda** fetches each company's XBRL `companyfacts` from SEC EDGAR. It runs at most
   5 at a time to respect SEC rate limits.
4. The worker saves the raw JSON to `raw/`, which expires after 30 days. It then writes normalized
   Parquet to `curated/facts/`, partitioned by fiscal year.
5. A final step records the run in DynamoDB and publishes CloudWatch metrics. Failures are retried,
   then sent to a dead-letter queue, and trigger an email alert.

The historical backfill runs once as an **ECS Fargate** task. It reads the SEC's bulk
`companyfacts.zip` instead of calling the API 500 times.

```
s3://edgar-lake-<account>/
  raw/companyfacts/dt=YYYY-MM-DD/cik=##########.json
  curated/facts/fiscal_year=YYYY/part-*.parquet
  curated/companies/companies.parquet
  config/sp500_ciks.csv
```

| Table | Key columns |
| --- | --- |
| `facts` | cik, ticker, metric, value, unit, fiscal_year, fiscal_period, period_end, form, filed_date, accession_no |
| `companies` | cik, ticker, name, sector, exchange |
| `sector_benchmarks` | Each metric's median per sector, recomputed nightly |

### Data quality

- **Tag mapping:** companies report the same concept under different XBRL tags, such as
  `Revenues` and `RevenueFromContractWithCustomerExcludingAssessedTax`. Each metric lists its tags
  in fallback order.
- **Deduplication:** every 10-K re-reports prior years. For each period, the latest-filed value
  wins, so restatements are picked up.
- **Fiscal labels:** in `companyfacts`, a value's fiscal year and period describe the filing it came
  from, not the period the number covers. Labels are taken from the earliest filing that reported
  each period.
- **Derived Q4:** companies don't file a Q4 10-Q. For flow metrics, Q4 is the full year minus
  Q1, Q2 and Q3.
- **Sector medians:** medians are used instead of averages, so one giant company doesn't skew the
  comparison.

### AI guardrails

The AI analyst writes SQL but never runs it unchecked:

1. The model answers at temperature 0, gets the schema plus a metric glossary, and returns SQL
   as JSON.
2. `sqlglot` parses the SQL and allows only one `SELECT` on approved tables and columns, with a
   `LIMIT` of 100 or less. Anything else is rejected.
3. The query runs in a read-only Athena workgroup with a per-query scan limit.
4. A second short model call explains the result in plain English. The UI shows the table, the
   explanation, the SQL and the "data as of" date.

Other safeguards: a daily quota per user, a global daily cap, and an AI kill switch stored in SSM.
Every number an answer gives must come from the data. The AI explains data and never recommends
buying or selling. A text-to-SQL eval set runs in CI whenever the prompts change.

### Security

- Cognito handles sign-in. API Gateway checks the JWT on the AI routes, and public routes are
  throttled.
- Each Lambda has its own IAM role, and the CI deploy role is limited to the `main` branch through
  OIDC, so no AWS keys are stored.
- S3 Block Public Access is on for every bucket, and CloudFront is the only reader of the site
  bucket.
- The app stores only an email address per user. There are no secrets: the SEC needs no API key.

### Cost

FinXplore is designed for **under $5/month**. Nearly everything fits in AWS's always-free
allowances. The remaining cost is mostly Bedrock tokens and Athena scans, which Parquet and
partitioning keep small. There are no NAT Gateways, Glue crawlers or always-on servers. AWS Budgets
emails an alert when spending passes $1, $5 and $10.

| Layer | Stack |
| --- | --- |
| Frontend | React, Vite, TypeScript, Recharts, TanStack Query, Vitest |
| Backend | Python 3.13 Lambdas, AWS Lambda Powertools, pandas/pyarrow, sqlglot |
| Data | S3 (Parquet), Glue Data Catalog, Athena, DynamoDB |
| AI | Amazon Bedrock (model chosen with the eval set) |
| Infra | Terraform (S3 remote state), GitHub Actions (OIDC to AWS) |

## Repository layout

```
.
├── backend/                 Python package `finxplore`
│   ├── src/finxplore/
│   │   ├── api/             API Lambda (Powertools HTTP resolver)
│   │   ├── ai/              SQL validator, prompt rules
│   │   ├── pipeline/        plan / worker / record_run Lambdas + fact extraction
│   │   ├── sec/             SEC EDGAR client (User-Agent, rate limit, retries)
│   │   ├── backfill/        one-time Fargate backfill
│   │   ├── metrics.py       core metrics + XBRL tag fallback mapping
│   │   └── config.py        settings from environment variables
│   ├── tests/               pytest (+ fixtures)
│   ├── evals/               AI text-to-SQL eval set
│   └── Dockerfile.backfill
├── frontend/                React + Vite app
├── infra/terraform/         bootstrap, envs/dev, modules
├── data/config/             S&P 500 CIK list (uploaded to s3://…/config/)
└── .github/workflows/       CI
```

## Getting started

### Prerequisites

- Python 3.12+ (3.13 matches the Lambda runtime)
- Node.js 22+
- Terraform 1.10+ and the AWS CLI v2 (only needed for deploying)
- Docker (only needed for the backfill image)

### 1. Environment variables

```bash
cp .env.example .env                       # backend / pipeline
cp frontend/.env.example frontend/.env.local
```

Set `SEC_USER_AGENT` to `"FinXplore your-email@example.com"`. The SEC requires a contact email
in the User-Agent and blocks requests without one.

### 2. Backend

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e ".[dev,pipeline]"
pytest            # run tests
ruff check .      # lint
ruff format .     # format
```

### 3. Frontend

```bash
cd frontend
npm install
npm run dev       # http://localhost:5173
npm test
npm run build
```

### 4. Infrastructure

See [infra/terraform/README.md](infra/terraform/README.md). Short version: apply `bootstrap/`
once, then `envs/dev/`. Budget alerts at $1, $5 and $10 are part of the first apply.

## Roadmap

| Phase | Goal | Status |
| --- | --- | --- |
| 0 | Repo, CI, Terraform state, budgets | In progress |
| 1 | Data lake, fact extraction, S&P 500 backfill | Started (extraction + tests) |
| 2 | Nightly pipeline, sector medians, monitoring | Not started |
| 3 | Website: search, company pages, tooltips, compare | Scaffolded |
| 4 | Sign-in, AI snapshot, "Explain this", AI analyst, quotas, feedback | SQL validator done |
| 5 | All SEC filers, data-quality engine, "What changed in this 10-K?" | Later |

## Data and compliance

- Data comes from SEC EDGAR's public [XBRL APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces).
- The pipeline follows SEC fair-access rules: it declares a User-Agent, caps requests at 5 per second, and uses the bulk file for large loads.
- Nothing on this site is investment advice. The AI explains data and never recommends buying or selling.
