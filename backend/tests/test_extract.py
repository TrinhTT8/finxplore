import json
from pathlib import Path

from finxplore.pipeline.extract import extract_facts

FIXTURE = Path(__file__).parent / "fixtures" / "companyfacts_sample.json"


def _load():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _rows(metric):
    return [r for r in extract_facts(_load(), ticker="AAPL") if r["metric"] == metric]


def test_dedup_keeps_latest_filed_value_but_original_fiscal_labels():
    fy2022 = [r for r in _rows("revenue") if r["period_end"] == "2022-09-24"]
    assert len(fy2022) == 1
    row = fy2022[0]
    assert row["value"] == 394328000000  # latest-filed (restated) value
    assert row["fiscal_year"] == 2022  # from the original 10-K, not the 2023 re-report
    assert row["fiscal_period"] == "FY"


def test_tag_fallback_prefers_first_tag():
    # Both tags report FY2023; the higher-priority tag's value wins.
    fy2023 = [r for r in _rows("revenue") if r["period_end"] == "2023-09-30"]
    assert [r["value"] for r in fy2023] == [383285000000]


def test_skips_ytd_periods_and_keeps_quarters():
    periods = {r["fiscal_period"] for r in _rows("revenue")}
    assert periods == {"FY", "Q1"}  # the 6-month YTD fact is skipped


def test_instant_metric():
    assets = _rows("total_assets")
    assert len(assets) == 1
    assert assets[0]["value"] == 352583000000
