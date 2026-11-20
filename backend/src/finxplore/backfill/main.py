"""One-time historical backfill (FR-3), run as an ECS Fargate task.

Downloads the SEC nightly bulk companyfacts.zip, filters to the CIK list, extracts
facts and writes Parquet to the curated layer.

Usage (local):  python -m finxplore.backfill.main --ciks ../data/config/sp500_ciks.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import zipfile
from pathlib import Path

from finxplore.pipeline.extract import extract_facts
from finxplore.sec.client import BULK_COMPANYFACTS_URL, pad_cik


def load_ciks(path: Path) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8") as f:
        return {pad_cik(r["cik"]): r["ticker"] for r in csv.DictReader(f)}


def iter_companyfacts(zip_path: Path, ciks: dict[str, str]):
    with zipfile.ZipFile(zip_path) as zf:
        for cik, ticker in ciks.items():
            name = f"CIK{cik}.json"
            try:
                with zf.open(name) as f:
                    yield ticker, json.load(f)
            except KeyError:
                print(f"missing in bulk file: {name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ciks", type=Path, required=True)
    parser.add_argument(
        "--zip",
        type=Path,
        default=Path("companyfacts.zip"),
        help=f"Local copy of {BULK_COMPANYFACTS_URL}",
    )
    args = parser.parse_args()

    total = 0
    for ticker, data in iter_companyfacts(args.zip, load_ciks(args.ciks)):
        rows = extract_facts(data, ticker=ticker)
        total += len(rows)
        # TODO: write rows to s3://<bucket>/curated/facts/fiscal_year=YYYY/ as Parquet
    print(f"extracted {total} facts")


if __name__ == "__main__":
    main()
