"""Step Functions 'plan' step: read the S&P 500 CIK list and enqueue one SQS job per company."""

from __future__ import annotations

import csv
import io
import json
import os

import boto3
from aws_lambda_powertools import Logger

from finxplore.config import get_settings

logger = Logger()
CIK_LIST_KEY = "config/sp500_ciks.csv"


@logger.inject_lambda_context
def handler(event: dict, context) -> dict:
    settings = get_settings()
    s3 = boto3.client("s3")
    sqs = boto3.client("sqs")
    queue_url = os.environ["PIPELINE_QUEUE_URL"]
    run_id = event.get("run_id") or context.aws_request_id

    body = s3.get_object(Bucket=settings.data_lake_bucket, Key=CIK_LIST_KEY)["Body"].read()
    companies = list(csv.DictReader(io.StringIO(body.decode("utf-8"))))

    for i in range(0, len(companies), 10):  # SQS batch limit is 10
        batch = companies[i : i + 10]
        sqs.send_message_batch(
            QueueUrl=queue_url,
            Entries=[
                {
                    "Id": str(j),
                    "MessageBody": json.dumps(
                        {"run_id": run_id, "cik": c["cik"], "ticker": c["ticker"]}
                    ),
                }
                for j, c in enumerate(batch)
            ],
        )

    logger.info("Queued companies", extra={"count": len(companies), "run_id": run_id})
    return {"run_id": run_id, "queued": len(companies)}
