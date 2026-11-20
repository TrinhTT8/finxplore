"""Turn one SEC companyfacts JSON document into normalized `facts` rows (FR-2).

Pure functions only (no AWS calls) so they are easy to unit test.

Data-quality rules implemented here:
- Tag mapping: per metric, tags are tried in priority order; first tag with a value wins.
- Deduplication: each 10-K re-reports prior years. For each (metric, period) keep the
  latest-filed value (picks up restatements).
- Fiscal labels: `fy`/`fp` in companyfacts describe the *filing*, not the period, so
  they are taken from the earliest filing that reported the period (its own 10-K/10-Q).

TODO (Phase 1): derive Q4 for flow metrics (FY - Q1 - Q2 - Q3) and free_cash_flow.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from finxplore.metrics import CORE_METRICS, Metric

ALLOWED_FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A"}


def _duration_days(fact: dict[str, Any]) -> int | None:
    if "start" not in fact:
        return None
    return (date.fromisoformat(fact["end"]) - date.fromisoformat(fact["start"])).days


def _period_type(metric: Metric, fact: dict[str, Any]) -> str | None:
    """Return 'annual' / 'quarter' for a fact, or None to skip it (e.g. 6- or 9-month YTD)."""
    if metric.kind == "instant":
        return "instant"
    days = _duration_days(fact)
    if days is None:
        return None
    if 350 <= days <= 380:
        return "annual"
    if 80 <= days <= 100:
        return "quarter"
    return None


def extract_facts(companyfacts: dict[str, Any], ticker: str | None = None) -> list[dict]:
    cik = str(companyfacts.get("cik", "")).zfill(10)
    us_gaap = companyfacts.get("facts", {}).get("us-gaap", {})
    rows: list[dict] = []

    for metric in CORE_METRICS:
        # (start, end) -> list of candidate facts for the winning tag
        periods: dict[tuple[str | None, str], list[dict]] = {}
        for tag in metric.tags:
            unit_facts = us_gaap.get(tag, {}).get("units", {}).get(metric.unit, [])
            tag_periods: dict[tuple[str | None, str], list[dict]] = {}
            for fact in unit_facts:
                if fact.get("form") not in ALLOWED_FORMS:
                    continue
                if _period_type(metric, fact) is None:
                    continue
                key = (fact.get("start"), fact["end"])
                tag_periods.setdefault(key, []).append(fact)
            for key, facts in tag_periods.items():
                periods.setdefault(key, facts)  # higher-priority tag already filled -> keep

        for (_start, end), facts in periods.items():
            latest = max(facts, key=lambda f: f["filed"])
            earliest = min(facts, key=lambda f: f["filed"])
            fiscal_year = earliest.get("fy")
            end_year = int(end[:4])
            if fiscal_year is None or abs(int(fiscal_year) - end_year) > 1:
                fiscal_year = end_year  # pre-XBRL comparatives: fall back to period end
            rows.append(
                {
                    "cik": cik,
                    "ticker": ticker,
                    "metric": metric.key,
                    "value": latest["val"],
                    "unit": metric.unit,
                    "fiscal_year": int(fiscal_year),
                    "fiscal_period": earliest.get("fp"),
                    "period_end": end,
                    "form": latest["form"],
                    "filed_date": latest["filed"],
                    "accession_no": latest["accn"],
                }
            )
    return rows
