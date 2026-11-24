import zipfile
from pathlib import Path

import pandas as pd
import pytest

from finxplore.backfill.main import load_overrides, load_predecessors, run_backfill

FIXTURE = Path(__file__).parent / "fixtures" / "companyfacts_sample.json"


def _inputs(tmp_path: Path) -> tuple[Path, Path]:
    """A one-company CIK list and a tiny stand-in for the SEC bulk companyfacts.zip."""
    ciks = tmp_path / "ciks.csv"
    ciks.write_text(
        "cik,ticker,name,sector,exchange\n"
        "0000320193,AAPL,Apple Inc.,Information Technology,Nasdaq\n",
        encoding="utf-8",
    )
    zip_path = tmp_path / "companyfacts.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("CIK0000320193.json", FIXTURE.read_text(encoding="utf-8"))
    return ciks, zip_path


def test_backfill_writes_one_parquet_file_per_fiscal_year(tmp_path):
    ciks, zip_path = _inputs(tmp_path)
    out = tmp_path / "curated"

    count = run_backfill(ciks, zip_path, out)

    assert count > 0
    files = sorted((out / "facts").glob("fiscal_year=*/part-backfill.parquet"))
    assert files
    df = pd.concat(pd.read_parquet(f) for f in files)
    assert len(df) == count
    assert "fiscal_year" not in df.columns  # partition key lives in the folder name
    assert df["value"].dtype == "float64"  # matches the Glue `double` column
    assert set(df["ticker"]) == {"AAPL"}


def test_backfill_writes_companies_with_padded_cik(tmp_path):
    ciks, zip_path = _inputs(tmp_path)
    out = tmp_path / "curated"

    run_backfill(ciks, zip_path, out)

    companies = pd.read_parquet(out / "companies" / "companies.parquet")
    assert companies.to_dict("records") == [
        {
            "cik": "0000320193",
            "ticker": "AAPL",
            "name": "Apple Inc.",
            "sector": "Information Technology",
            "exchange": "Nasdaq",
        }
    ]


def test_predecessor_history_is_stored_under_the_current_cik(tmp_path):
    # New holding company (like ExxonMobil Holdings) with no facts yet; history lives under
    # the predecessor CIK. Reuse the Apple fixture as that "old" history.
    ciks = tmp_path / "ciks.csv"
    ciks.write_text(
        "cik,ticker,name,sector,exchange\n0002115436,XOM,ExxonMobil,Energy,NYSE\n",
        encoding="utf-8",
    )
    predecessors = tmp_path / "predecessors.csv"
    predecessors.write_text(
        "cik,predecessor_cik,note\n0002115436,0000320193,test\n", encoding="utf-8"
    )
    zip_path = tmp_path / "companyfacts.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("CIK0002115436.json", '{"cik": 2115436, "facts": {"us-gaap": {}}}')
        zf.writestr("CIK0000320193.json", FIXTURE.read_text(encoding="utf-8"))
    out = tmp_path / "curated"

    with_history = run_backfill(ciks, zip_path, out, predecessors)
    without_history = run_backfill(ciks, zip_path, tmp_path / "plain")

    assert without_history == 0
    assert with_history > 0
    df = pd.concat(pd.read_parquet(f) for f in (out / "facts").glob("*/*.parquet"))
    assert set(df["cik"]) == {"0002115436"}
    assert set(df["ticker"]) == {"XOM"}


def test_rerun_removes_stale_years(tmp_path):
    ciks, zip_path = _inputs(tmp_path)
    out = tmp_path / "curated"
    stale = out / "facts" / "fiscal_year=1999" / "part-backfill.parquet"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"old")

    run_backfill(ciks, zip_path, out)

    assert not stale.exists()


def test_load_overrides_parses_pipe_separated_tags(tmp_path):
    path = tmp_path / "overrides.csv"
    path.write_text(
        "cik,metric,tags,note\n2012383,revenue, TagA | TagB ,test\n",  # unpadded CIK, spaces
        encoding="utf-8",
    )
    assert load_overrides(path) == {"0002012383": {"revenue": ("TagA", "TagB")}}


def test_load_overrides_missing_file_means_no_overrides(tmp_path):
    assert load_overrides(tmp_path / "nope.csv") == {}


def test_load_overrides_rejects_unknown_metric(tmp_path):
    path = tmp_path / "overrides.csv"
    path.write_text("cik,metric,tags,note\n2012383,revenues,TagA,typo\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown metric 'revenues'"):
        load_overrides(path)


def test_backfill_applies_overrides_by_current_cik(tmp_path):
    ciks, zip_path = _inputs(tmp_path)  # Apple fixture: Revenues (400B) beats contract (383B)
    overrides = tmp_path / "overrides.csv"
    overrides.write_text(
        "cik,metric,tags,note\n"
        "0000320193,revenue,RevenueFromContractWithCustomerExcludingAssessedTax,test\n",
        encoding="utf-8",
    )
    out = tmp_path / "curated"

    run_backfill(ciks, zip_path, out, overrides_path=overrides)

    df = pd.concat(pd.read_parquet(f) for f in (out / "facts").glob("*/*.parquet"))
    fy2023 = df[(df.metric == "revenue") & (df.period_end == "2023-09-30")]
    assert fy2023["value"].tolist() == [383285000000.0]


def test_real_config_files_load():
    # Guards the checked-in CSVs against header typos and unknown metric names.
    config = Path(__file__).resolve().parents[2] / "data" / "config"
    overrides = load_overrides(config / "metric_overrides.csv")
    predecessors = load_predecessors(config / "cik_predecessors.csv")
    assert overrides and predecessors
    assert all(len(cik) == 10 for cik in [*overrides, *predecessors])
