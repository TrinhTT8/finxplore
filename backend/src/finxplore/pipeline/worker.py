"""SQS worker Lambda: fetch one company's companyfacts, save raw JSON, write curated Parquet.

Reserved concurrency (set in Terraform) caps this at 5 to respect SEC rate limits.
Failed messages are retried by SQS and then land in the dead-letter queue.
"""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.batch import (
    BatchProcessor,
    EventType,
    process_partial_response,
)
from aws_lambda_powertools.utilities.data_classes.sqs_event import SQSRecord

from finxplore.config import get_settings
from finxplore.pipeline.extract import extract_facts
from finxplore.sec.client import SecClient, pad_cik

logger = Logger()
processor = BatchProcessor(event_type=EventType.SQS)
_s3 = boto3.client("s3")
_sec: SecClient | None = None


def _sec_client() -> SecClient:
    global _sec
    if _sec is None:
        _sec = SecClient()
    return _sec


def _write_parquet(rows: list[dict], bucket: str, key: str) -> None:
    import pandas as pd  # provided by the AWS SDK for pandas layer

    buf = io.BytesIO()
    pd.DataFrame(rows).to_parquet(buf, index=False)
    _s3.put_object(Bucket=bucket, Key=key, Body=buf.getvalue())


def process_company(cik: str, ticker: str) -> int:
    settings = get_settings()
    bucket = settings.data_lake_bucket
    cik10 = pad_cik(cik)
    dt = datetime.now(UTC).strftime("%Y-%m-%d")

    data = _sec_client().companyfacts(cik10)
    # TODO: skip unchanged companies (compare latest filed date with last run).
    _s3.put_object(
        Bucket=bucket,
        Key=f"raw/companyfacts/dt={dt}/cik={cik10}.json",
        Body=json.dumps(data).encode("utf-8"),
    )

    rows = extract_facts(data, ticker=ticker)
    # TODO: write per fiscal_year partition (curated/facts/fiscal_year=YYYY/part-<cik>.parquet)
    _write_parquet(rows, bucket, f"curated/facts/_staging/cik={cik10}.parquet")
    logger.info("Processed company", extra={"cik": cik10, "rows": len(rows)})
    return len(rows)


def record_handler(record: SQSRecord) -> None:
    msg = json.loads(record.body)
    process_company(msg["cik"], msg["ticker"])


@logger.inject_lambda_context
def handler(event: dict, context):
    return process_partial_response(
        event=event, record_handler=record_handler, processor=processor, context=context
    )
