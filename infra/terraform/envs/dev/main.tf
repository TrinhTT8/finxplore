terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
  # Configured at init time: terraform init -backend-config=backend.hcl
  # (S3 native state locking via use_lockfile; no DynamoDB lock table needed)
  backend "s3" {}
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project     = "finxplore"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  name_prefix = "finxplore-${var.environment}"
}

# ---------- Phase 0: cost guardrails ----------
module "budgets" {
  source      = "../../modules/budgets"
  name_prefix = local.name_prefix
  alert_email = var.alert_email
  thresholds  = [1, 5, 10]
}

# ---------- Phase 1: data lake ----------
module "data_lake" {
  source             = "../../modules/data_lake"
  bucket_name        = "edgar-lake-${data.aws_caller_identity.current.account_id}"
  glue_database      = var.glue_database
  raw_retention_days = 30
}

# ---------- Later phases (see infra/terraform/README.md) ----------
# module "athena"       -> app + ai-readonly workgroups, Glue tables with partition projection
# module "pipeline"     -> EventBridge Scheduler, Step Functions, SQS + DLQ, worker Lambdas
# module "app_tables"   -> DynamoDB Users, QueryCache, Watchlists, PipelineRuns
# module "api"          -> API Gateway HTTP API, API Lambda, JWT authorizer
# module "auth"         -> Cognito user pool + app client
# module "frontend"     -> S3 site bucket + CloudFront (OAC)
# module "monitoring"   -> CloudWatch dashboard, alarms, SNS email
# module "github_oidc"  -> GitHub Actions OIDC role scoped to this repo's main branch
