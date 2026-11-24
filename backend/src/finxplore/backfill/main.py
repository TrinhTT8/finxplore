"""One-time historical backfill (FR-3), run as an ECS Fargate task.

Downloads the SEC nightly bulk companyfacts.zip, filters to the CIK list, extracts
facts and writes Parquet to the curated layer.

Output layout (mirrors s3://<bucket>/curated/, so it can be uploaded with `aws s3 sync`):
    <out-dir>/facts/fiscal_year=YYYY/part-backfill.parquet
    <out-dir>/companies/companies.parquet

Usage (local, from backend/):
    python -m finxplore.backfill.main --ciks ../data/config/sp500_ciks.csv \
        --zip ../data/tmp/companyfacts.zip --out-dir ../data/curated
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import zipfile
from pathlib import Path

from finxplore.metrics import METRICS_BY_KEY
from finxplore.pipeline.extract import extract_facts, merge_companyfacts
from finxplore.sec.client import BULK_COMPANYFACTS_URL, pad_cik

FACTS_FILE_NAME = "part-backfill.parquet"


def load_ciks(path: Path) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8") as f:
        return {pad_cik(r["cik"]): r["ticker"] for r in csv.DictReader(f)}


def load_predecessors(path: Path | None) -> dict[str, list[str]]:
    """Map current CIK -> predecessor CIKs. A missing file means no predecessors."""
    if path is None or not path.is_file():
        return {}
    result: dict[str, list[str]] = {}
    with path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            result.setdefault(pad_cik(r["cik"]), []).append(pad_cik(r["predecessor_cik"]))
    return result


def load_overrides(path: Path | None) -> dict[str, dict[str, tuple[str, ...]]]:
    """Map CIK -> {metric: tags} from metric_overrides.csv. A missing file means no overrides.

    `tags` is a `|`-separated priority list that replaces the metric's default tags for that
    company. An unknown metric name is an error, so a typo can't silently do nothing.
    """
    if path is None or not path.is_file():
        return {}
    result: dict[str, dict[str, tuple[str, ...]]] = {}
    with path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            metric = r["metric"].strip()
            if metric not in METRICS_BY_KEY:
                raise ValueError(f"unknown metric {metric!r} in {path}")
            tags = tuple(t.strip() for t in r["tags"].split("|") if t.strip())
            if not tags:
                raise ValueError(f"no tags for {r['cik']}/{metric} in {path}")
            result.setdefault(pad_cik(r["cik"]), {})[metric] = tags
    return result


def _read_member(zf: zipfile.ZipFile, cik: str) -> dict | None:
    try:
        with zf.open(f"CIK{cik}.json") as f:
            return json.load(f)
    except KeyError:
        print(f"missing in bulk file: CIK{cik}.json")
        return None


def iter_companyfacts(
    zip_path: Path, ciks: dict[str, str], predecessors: dict[str, list[str]] | None = None
):
    """Yield (ticker, companyfacts) per company, merged with any predecessor CIKs' history."""
    predecessors = predecessors or {}
    with zipfile.ZipFile(zip_path) as zf:
        for cik, ticker in ciks.items():
            data = _read_member(zf, cik)
            if data is None:
                continue
            older = [d for p in predecessors.get(cik, []) if (d := _read_member(zf, p))]
            yield ticker, merge_companyfacts(data, older) if older else data


def write_facts(rows: list[dict], out_dir: Path) -> list[Path]:
    """Write one Parquet file per fiscal year under out_dir/facts/. Returns the paths written."""
    import pandas as pd  # optional "pipeline" dependency

    facts_dir = out_dir / "facts"
    shutil.rmtree(facts_dir, ignore_errors=True)  # idempotent: reruns never leave stale years
    if not rows:
        return []

    df = pd.DataFrame(rows)
    df["value"] = df["value"].astype("float64")  # Glue column type is double
    text_columns = df.columns.difference(["value", "fiscal_year"])
    df[text_columns] = df[text_columns].astype("string")  # stays string even if all values are null

    paths = []
    for year, group in df.groupby("fiscal_year"):
        path = facts_dir / f"fiscal_year={int(year)}" / FACTS_FILE_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        # fiscal_year is the partition key: it lives in the folder name, not in the file
        group.drop(columns="fiscal_year").to_parquet(path, index=False)
        paths.append(path)
    return paths


def write_companies(ciks_path: Path, out_dir: Path) -> Path:
    """Convert the company list CSV into out_dir/companies/companies.parquet."""
    import pandas as pd

    df = pd.read_csv(ciks_path, dtype=str, keep_default_na=False)  # keep CIK leading zeros
    df["cik"] = df["cik"].map(pad_cik)
    path = out_dir / "companies" / "companies.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path


def run_backfill(
    ciks_path: Path,
    zip_path: Path,
    out_dir: Path,
    predecessors_path: Path | None = None,
    overrides_path: Path | None = None,
) -> int:
    """Extract facts for every company and write curated Parquet. Returns the row count."""
    all_rows: list[dict] = []
    companies = 0
    predecessors = load_predecessors(predecessors_path)
    overrides = load_overrides(overrides_path)
    for ticker, data in iter_companyfacts(zip_path, load_ciks(ciks_path), predecessors):
        # data["cik"] is the current CIK even after merging predecessors
        company_overrides = overrides.get(pad_cik(data["cik"]))
        all_rows.extend(extract_facts(data, ticker=ticker, overrides=company_overrides))
        companies += 1

    fact_files = write_facts(all_rows, out_dir)
    write_companies(ciks_path, out_dir)
    print(
        f"extracted {len(all_rows)} facts from {companies} companies "
        f"into {len(fact_files)} fiscal-year files under {out_dir}"
    )
    return len(all_rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--ciks", type=Path, required=True)
    parser.add_argument(
        "--zip",
        type=Path,
        default=Path("companyfacts.zip"),
        help=f"Local copy of {BULK_COMPANYFACTS_URL}",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("../data/curated"),
        help="Where to write curated Parquet (same layout as s3://<bucket>/curated/)",
    )
    parser.add_argument(
        "--predecessors",
        type=Path,
        default=Path("../data/config/cik_predecessors.csv"),
        help="CSV of cik,predecessor_cik pairs whose history is merged in (optional)",
    )
    parser.add_argument(
        "--overrides",
        type=Path,
        default=Path("../data/config/metric_overrides.csv"),
        help="CSV of per-company tag overrides: cik,metric,tags(|-separated),note (optional)",
    )
    args = parser.parse_args()
    run_backfill(args.ciks, args.zip, args.out_dir, args.predecessors, args.overrides)


if __name__ == "__main__":
    main()
