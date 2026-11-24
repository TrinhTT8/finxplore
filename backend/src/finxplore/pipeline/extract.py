"""Turn one SEC companyfacts JSON document into normalized `facts` rows (FR-2).

Pure functions only (no AWS calls) so they are easy to unit test.

Data-quality rules implemented here:
- Tag mapping: per metric, tags are tried in priority order; first tag with a value wins,
  unless it is under half of a known component tag (Metric.component_tags) for that period,
  which means the company used it for only part of the metric.
- Deduplication: each 10-K re-reports prior years. For each (metric, period) keep the
  latest-filed value (picks up restatements).
- Fiscal labels: `fy`/`fp` in companyfacts describe the *filing*, not the period, so
  they are taken from the earliest filing that reported the period (its own 10-K/10-Q).
  A value first seen a year or more later is a comparative, so its year is moved back.
  fiscal_period follows the period length: ~1 year -> FY, a quarter first seen in a
  10-K -> Q4 (a 10-K's own `fp` is FY even for the 3-month Q4 figures inside it).
- Predecessor CIKs: after a reorganization (e.g. a new holding company) the history stays
  under the old CIK. merge_companyfacts() pools both documents before extraction, so the
  dedup rule above still picks the latest-filed value for any period both report.

TODO (Phase 1): derive Q4 for flow metrics (FY - Q1 - Q2 - Q3) and free_cash_flow.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from finxplore.metrics import COMPONENT_FLOOR, CORE_METRICS, Metric

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


def _latest_value(facts: list[dict[str, Any]]) -> float:
    return max(facts, key=lambda f: f["filed"])["val"]


def _choose_tag(metric: Metric, candidates: list[tuple[str, list[dict]]]) -> list[dict]:
    """Pick the facts of the first tag that reports this period, skipping a tag whose value
    is implausibly small next to a known component of the metric (see Metric.component_tags).
    """
    component_values = [
        _latest_value(facts) for tag, facts in candidates if tag in metric.component_tags
    ]
    floor = COMPONENT_FLOOR * max(component_values) if component_values else None
    for _tag, facts in candidates:
        if floor is None or floor <= 0 or _latest_value(facts) >= floor:
            return facts
    return candidates[0][1]


def _years_late(fact: dict[str, Any], end: str) -> int:
    """How many years after the period this filing came out (0 = the period's own report).

    Companies file within ~3 months of a period end; a value first seen ~1 year later is a
    prior-year comparative (common for periods before the company's first XBRL filing).
    """
    lag_days = (date.fromisoformat(fact["filed"]) - date.fromisoformat(end)).days
    return max(0, round((lag_days - 60) / 365))


def _fiscal_year(earliest: dict[str, Any], end: str) -> int:
    """The `fy` of the filing that first reported the period, moved back by one year for
    each year that filing came after the period (a comparative carries the newer year)."""
    fy = earliest.get("fy")
    end_year = int(end[:4])
    if fy is None:
        return end_year
    fiscal_year = int(fy) - _years_late(earliest, end)
    return fiscal_year if abs(fiscal_year - end_year) <= 1 else end_year


def _fiscal_period(metric: Metric, earliest: dict[str, Any]) -> str | None:
    """FY for ~1-year periods. For ~3-month periods, the 10-Q's own label (Q1-Q3), or Q4 when
    the quarter first appeared in a 10-K: there is no Q4 10-Q, and a 10-K's `fp` is always FY.
    """
    period_type = _period_type(metric, earliest)
    if period_type == "annual":
        return "FY"
    if period_type == "quarter":
        fp = earliest.get("fp")
        return fp if fp in ("Q1", "Q2", "Q3") else "Q4"
    return earliest.get("fp") or None  # instant: label of the filing it came from


def merge_companyfacts(
    current: dict[str, Any], predecessors: list[dict[str, Any]]
) -> dict[str, Any]:
    """Combine a company's companyfacts with those of its predecessor registrants.

    Fact lists are concatenated per taxonomy/tag/unit; everything else (cik, entityName)
    comes from `current`, so extracted rows are stored under the current CIK.
    """
    facts: dict[str, dict[str, Any]] = {}
    for doc in [current, *predecessors]:
        for taxonomy, tags in doc.get("facts", {}).items():
            for tag, body in tags.items():
                entry = facts.setdefault(taxonomy, {}).setdefault(
                    tag, {**{k: v for k, v in body.items() if k != "units"}, "units": {}}
                )
                for unit, items in body.get("units", {}).items():
                    entry["units"].setdefault(unit, []).extend(items)
    return {**current, "facts": facts}


def extract_facts(companyfacts: dict[str, Any], ticker: str | None = None) -> list[dict]:
    cik = str(companyfacts.get("cik", "")).zfill(10)
    us_gaap = companyfacts.get("facts", {}).get("us-gaap", {})
    rows: list[dict] = []

    for metric in CORE_METRICS:
        # One {(period_type, end): [facts]} map per tag, in priority order. Keyed by end date
        # and length, not start date: filings sometimes disagree on the start by a day
        # (2009-01-01 vs 2008-12-31), which would otherwise split one period into two rows.
        by_tag: list[tuple[str, dict[tuple[str, str], list[dict]]]] = []
        for tag in metric.tags:
            unit_facts = us_gaap.get(tag, {}).get("units", {}).get(metric.unit, [])
            tag_periods: dict[tuple[str, str], list[dict]] = {}
            for fact in unit_facts:
                if fact.get("form") not in ALLOWED_FORMS:
                    continue
                period_type = _period_type(metric, fact)
                if period_type is None:
                    continue
                tag_periods.setdefault((period_type, fact["end"]), []).append(fact)
            by_tag.append((tag, tag_periods))

        all_periods = dict.fromkeys(key for _, tp in by_tag for key in tp)  # ordered union
        for key in all_periods:
            candidates = [(tag, tp[key]) for tag, tp in by_tag if key in tp]
            facts = _choose_tag(metric, candidates)
            _period_type_key, end = key
            latest = max(facts, key=lambda f: f["filed"])
            earliest = min(facts, key=lambda f: f["filed"])
            rows.append(
                {
                    "cik": cik,
                    "ticker": ticker,
                    "metric": metric.key,
                    "value": latest["val"],
                    "unit": metric.unit,
                    "fiscal_year": _fiscal_year(earliest, end),
                    "fiscal_period": _fiscal_period(metric, earliest),
                    "period_end": end,
                    "form": latest["form"],
                    "filed_date": latest["filed"],
                    "accession_no": latest["accn"],
                }
            )
    return rows
