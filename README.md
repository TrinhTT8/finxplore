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

The S3 data lake is the single source of truth. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
for the full design, requirements, cost estimate and roadmap.

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
├── docs/ARCHITECTURE.md     design doc
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
