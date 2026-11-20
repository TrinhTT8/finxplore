"""Final Step Functions step: record the run in DynamoDB `PipelineRuns` and publish metrics."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import boto3
from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.metrics import MetricUnit

logger = Logger()
metrics = Metrics(namespace="FinXplore")


@metrics.log_metrics
@logger.inject_lambda_context
def handler(event: dict, context) -> dict:
    table = boto3.resource("dynamodb").Table(os.environ["DDB_PIPELINE_RUNS_TABLE"])
    item = {
        "run_id": event["run_id"],
        "finished_at": datetime.now(UTC).isoformat(),
        "queued": event.get("queued", 0),
        "failed": event.get("failed", 0),
        "status": "FAILED" if event.get("failed") else "SUCCEEDED",
    }
    table.put_item(Item=item)
    metrics.add_metric(name="CompaniesQueued", unit=MetricUnit.Count, value=item["queued"])
    metrics.add_metric(name="CompaniesFailed", unit=MetricUnit.Count, value=item["failed"])
    return item
