# Infrastructure (Terraform)

All AWS infrastructure lives here. Nothing is created by hand.

```
bootstrap/        one-time: remote-state bucket (local state)
envs/dev/         the dev environment, composes the modules
modules/
  budgets/        AWS Budgets alerts at $1 / $5 / $10          (Phase 0, done)
  data_lake/      S3 lake + lifecycle + Glue database          (Phase 1, done)
```

## First-time setup

```bash
# 1. Remote state bucket (once per AWS account)
cd infra/terraform/bootstrap
terraform init
terraform apply

# 2. Dev environment
cd ../envs/dev
cp backend.hcl.example backend.hcl            # fill in the state bucket name
cp terraform.tfvars.example terraform.tfvars  # fill in alert_email
terraform init -backend-config=backend.hcl
terraform plan
terraform apply
```

State locking uses S3's native lock file (`use_lockfile = true`, Terraform 1.10+), so no
DynamoDB lock table is needed.

## Modules still to build

| Module | Contents | Phase |
| --- | --- | --- |
| `athena` | `finxplore-app` and `ai-readonly` workgroups (100 MB scan limit), Glue tables `facts` / `companies` / `sector_benchmarks` with partition projection | 1 |
| `pipeline` | EventBridge Scheduler, Step Functions, SQS + DLQ, plan/worker/record-run Lambdas (worker reserved concurrency 5) | 2 |
| `app_tables` | DynamoDB `Users`, `QueryCache` (TTL), `Watchlists`, `PipelineRuns` (provisioned, low capacity) | 2 |
| `monitoring` | CloudWatch dashboard, alarms, SNS email topic, X-Ray | 2 |
| `github_oidc` | GitHub Actions OIDC provider + deploy role limited to this repo's `main` branch | 2 |
| `api` | API Gateway HTTP API, API Lambda, throttling, Cognito JWT authorizer on `/ai/*` | 3 |
| `frontend` | Private S3 site bucket + CloudFront with Origin Access Control | 3 |
| `auth` | Cognito user pool (email sign-in) + app client | 4 |
| `backfill` | ECR repo + ECS Fargate task definition | 1 |
| `config` | SSM parameters, including the AI kill switch | 4 |

## Cost rules

- No NAT Gateway: Lambdas run outside a VPC.
- No Glue crawlers: tables are defined here with partition projection.
- Every Lambda gets reserved concurrency; Athena workgroups have per-query scan limits.
