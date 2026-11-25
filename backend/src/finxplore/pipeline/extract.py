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
  Annual periods then use one company-wide convention (_fiscal_year_offset), because the
  `fy` field itself is sometimes wrong, and quarters take the year of the annual period
  that contains them (_relabel).
  fiscal_period follows the period length: ~1 year -> FY, a quarter first seen in a
  10-K -> Q4 (a 10-K's own `fp` is FY even for the 3-month Q4 figures inside it).
- Predecessor CIKs: after a reorganization (e.g. a new holding company) the history stays
  under the old CIK. merge_companyfacts() pools both documents before extraction, so the
  dedup rule above still picks the latest-filed value for any period both report.
- Derived quarters: missing quarters of flow metrics are calculated from year-to-date and
  annual figures (see _derive_quarters) and stored with form = "derived".
- free_cash_flow = operating_cash_flow - capex for every period with both (form "derived").
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import replace
from datetime import date, timedelta
from typing import Any

from finxplore.metrics import COMPONENT_FLOOR, CORE_METRICS, Metric

ALLOWED_FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A"}
ANNUAL_FORMS = {"10-K", "10-K/A"}


def _duration_days(fact: dict[str, Any]) -> int | None:
    if "start" not in fact:
        return None
    return (date.fromisoformat(fact["end"]) - date.fromisoformat(fact["start"])).days


def _period_type(metric: Metric, fact: dict[str, Any]) -> str | None:
    """Return 'annual' / 'quarter' / 'ytd6' / 'ytd9' for a fact, or None to skip it.

    ytd6/ytd9 are 6- and 9-month year-to-date figures (10-Qs report cash flow this way).
    They are only kept for flow metrics, used to derive quarters, and never output as rows.
    """
    if metric.kind == "instant":
        return "instant"
    days = _duration_days(fact)
    if days is None:
        return None
    if 350 <= days <= 380:
        return "annual"
    if 80 <= days <= 100:
        return "quarter"
    if metric.kind == "flow" and 165 <= days <= 195:
        return "ytd6"
    if metric.kind == "flow" and 255 <= days <= 285:
        return "ytd9"
    return None


ROW_PERIOD_TYPES = {"annual", "quarter", "instant"}
DERIVED_FORM = "derived"  # `form` value marking calculated rows (no SEC filing reports them)
QUARTER_DAYS = 91.3
DATE_TOLERANCE_DAYS = 10  # filings disagree on period start/end dates by a few days


def _d(iso: str) -> date:
    return date.fromisoformat(iso)


def _quarter_of_year(year: dict[str, Any], period: dict[str, Any]) -> int | None:
    """Which quarter (1-4) of fiscal `year` a period ends in, by dates; None if outside it."""
    tol = timedelta(DATE_TOLERANCE_DAYS)
    start, end = _d(year["start"]), _d(year["end"])
    if not (start - tol <= _d(period["start"]) and _d(period["end"]) <= end + tol):
        return None
    k = round((_d(period["end"]) - start).days / QUARTER_DAYS)
    return k if 1 <= k <= 4 else None


def _balance_date_quarter(year: dict[str, Any], end: str) -> int | None:
    """Which quarter-end (1-4) of fiscal `year` a balance-sheet date falls on, or None.
    A balance on the year's first day belongs to the previous year's end, so it's excluded."""
    tol = timedelta(DATE_TOLERANCE_DAYS)
    start, year_end, d = _d(year["start"]), _d(year["end"]), _d(end)
    if not (start + tol < d <= year_end + tol):
        return None
    k = round((d - start).days / QUARTER_DAYS)
    return k if 1 <= k <= 4 else None


def _fiscal_calendar(chosen_by_metric: list[tuple[Metric, list[dict]]]) -> list[dict[str, Any]]:
    """The company's fiscal years (one annual period per fiscal_year), pooled from all metrics
    so that every metric, including balance-sheet ones, is labelled on the same calendar."""
    calendar: dict[int, dict[str, Any]] = {}
    for _metric, chosen in chosen_by_metric:
        for p in chosen:
            if p["type"] == "annual" and p["start"]:
                calendar.setdefault(p["fiscal_year"], p)
    return sorted(calendar.values(), key=lambda p: p["end"])


def _relabel(periods: list[dict[str, Any]], calendar: list[dict[str, Any]]) -> None:
    """Label quarters and balance-sheet dates by their position in the company's calendar.

    Filing labels are unreliable: a 10-K's quarterly-data table and its prior-period balance
    sheet carry the 10-K's own `fp` (FY) and `fy`, so a December quarter could be labelled
    "Q4 of next year". Periods outside every known fiscal year keep their filing label.
    """
    for p in periods:
        for year in calendar:
            if p["type"] == "quarter" and p["start"]:
                k = _quarter_of_year(year, p)
                label = f"Q{k}" if k else None
            elif p["type"] == "instant":
                k = _balance_date_quarter(year, p["end"])
                label = ("FY" if k == 4 else f"Q{k}") if k else None
            else:
                break
            if label:
                p["fiscal_year"], p["fiscal_period"] = year["fiscal_year"], label
                break


def _derive_quarters(metric: Metric, periods: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Calculate missing quarters of a flow metric from year-to-date and annual figures.

        Q2 = 6-month YTD - Q1      Q3 = 9-month YTD - 6-month YTD      Q4 = FY - 9-month YTD
        (when a YTD figure is missing, it is rebuilt by adding up the reported quarters)

    Quarters are placed in a fiscal year by their dates, not by fiscal labels. A reported
    quarter is never replaced. For non-negative metrics, a result below zero or above the
    full year means the inputs don't fit together (e.g. a restated year next to
    unrestated quarters), so it is dropped rather than stored.
    """
    derived: list[dict[str, Any]] = []
    for year in (p for p in periods if p["type"] == "annual" and p["start"]):
        start = _d(year["start"])
        quarters: dict[int, dict] = {}  # quarter number -> reported 3-month period
        ytd: dict[int, dict] = {}  # quarter number -> cumulative period starting at `start`
        for p in periods:
            if p["type"] == "annual" or not p["start"]:
                continue
            k = _quarter_of_year(year, p)
            if k is None:
                continue  # not inside this fiscal year
            from_year_start = abs((_d(p["start"]) - start).days) <= DATE_TOLERANCE_DAYS
            if p["type"] == "quarter":
                quarters[k] = p
                if k == 1 and from_year_start:
                    ytd[1] = p  # Q1 is also the 3-month year-to-date figure
            elif from_year_start and (p["type"], k) in (("ytd6", 2), ("ytd9", 3)):
                ytd[k] = p

        # cumulative[k] = (value through quarter k, end date, filing dates used)
        cumulative: dict[int, tuple[float, str, list[str]]] = {0: (0.0, "", [])}
        for k in (1, 2, 3, 4):
            source = year if k == 4 else ytd.get(k)
            if source is not None:
                cumulative[k] = (source["value"], source["end"], [source["filed"]])
            elif k - 1 in cumulative and k in quarters:
                prev_value, _, prev_filed = cumulative[k - 1]
                q = quarters[k]
                cumulative[k] = (prev_value + q["value"], q["end"], [*prev_filed, q["filed"]])

        for k in (2, 3, 4):
            if k in quarters or k not in cumulative or k - 1 not in cumulative:
                continue
            value = cumulative[k][0] - cumulative[k - 1][0]
            if metric.non_negative and not (0 <= value <= year["value"]):
                continue
            derived.append(
                {
                    "fiscal_year": year["fiscal_year"],
                    "fiscal_period": f"Q{k}",
                    "period_end": cumulative[k][1],
                    "value": value,
                    "filed_date": max(cumulative[k][2] + cumulative[k - 1][2]),
                }
            )
    return derived


def _free_cash_flow(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """free_cash_flow = operating_cash_flow - capex, for every period that has both."""
    by_period: dict[str, dict[tuple, dict]] = {"operating_cash_flow": {}, "capex": {}}
    for r in rows:
        if r["metric"] in by_period:
            by_period[r["metric"]][(r["fiscal_period"], r["period_end"])] = r
    ocf, capex = by_period["operating_cash_flow"], by_period["capex"]
    return [
        {
            **ocf[key],
            "metric": "free_cash_flow",
            "value": ocf[key]["value"] - capex[key]["value"],
            "form": DERIVED_FORM,
            "filed_date": max(ocf[key]["filed_date"], capex[key]["filed_date"]),
            "accession_no": None,
        }
        for key in ocf
        if key in capex
    ]


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


def _anchor_year(end: str) -> int:
    """Calendar year a fiscal year 'belongs to': 52/53-week years can end a few days into
    January (Snap-on's fiscal 2025 ended 2026-01-03), so look two weeks before the end."""
    return (_d(end) - timedelta(days=14)).year


def _fiscal_year_offset(us_gaap: dict[str, Any]) -> int | None:
    """The company's naming convention: fiscal year = _anchor_year(end) + offset.

    Learned from annual figures in the company's *own* 10-Ks (filed within ~a year of the
    period), taking the most common offset. Most companies use 0; some retailers whose year
    ends in January use -1 (Target calls the year ending 2026-01-31 "fiscal 2025"). Using
    one offset for every year fixes filings whose `fy` field is simply wrong, which gave two
    different years the same label. Returns None if there is nothing to learn from.
    """
    counts: Counter[int] = Counter()
    for metric in CORE_METRICS:
        if metric.kind == "instant":
            continue
        for tag in metric.tags:
            for fact in us_gaap.get(tag, {}).get("units", {}).get(metric.unit, []):
                if fact.get("form") not in ANNUAL_FORMS or fact.get("fy") is None:
                    continue
                if _period_type(metric, fact) != "annual" or _years_late(fact, fact["end"]):
                    continue
                counts[int(fact["fy"]) - _anchor_year(fact["end"])] += 1
    return counts.most_common(1)[0][0] if counts else None


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


def extract_facts(
    companyfacts: dict[str, Any],
    ticker: str | None = None,
    overrides: Mapping[str, tuple[str, ...]] | None = None,
) -> list[dict]:
    """Normalized `facts` rows for one company.

    overrides: optional {metric_key: tags} for this company (data/config/metric_overrides.csv).
    The tags replace the metric's default priority list, and the component floor is switched
    off: a person has already checked which tag is right for this company.
    """
    cik = str(companyfacts.get("cik", "")).zfill(10)
    us_gaap = companyfacts.get("facts", {}).get("us-gaap", {})
    rows: list[dict] = []
    overrides = overrides or {}
    year_offset = _fiscal_year_offset(us_gaap)

    # Pass 1: choose each metric's value for every period
    chosen_by_metric: list[tuple[Metric, list[dict[str, Any]]]] = []
    for default_metric in CORE_METRICS:
        metric = default_metric
        if metric.key in overrides:
            metric = replace(metric, tags=tuple(overrides[metric.key]), component_tags=())
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
                if period_type == "annual" and fact["form"] not in ANNUAL_FORMS:
                    continue  # 12 months in a 10-Q = trailing twelve months, not a fiscal year
                tag_periods.setdefault((period_type, fact["end"]), []).append(fact)
            by_tag.append((tag, tag_periods))

        all_periods = dict.fromkeys(key for _, tp in by_tag for key in tp)  # ordered union
        chosen: list[dict[str, Any]] = []  # every chosen period, incl. YTD (for derivation)
        for key in all_periods:
            candidates = [(tag, tp[key]) for tag, tp in by_tag if key in tp]
            facts = _choose_tag(metric, candidates)
            period_type, end = key
            latest = max(facts, key=lambda f: f["filed"])
            earliest = min(facts, key=lambda f: f["filed"])
            chosen.append(
                {
                    "type": period_type,
                    "start": latest.get("start"),
                    "end": end,
                    "value": latest["val"],
                    "filed": latest["filed"],
                    "fiscal_year": _fiscal_year(earliest, end),
                    "fiscal_period": _fiscal_period(metric, earliest),
                    "form": latest["form"],
                    "accn": latest["accn"],
                }
            )
        if year_offset is not None:
            for p in chosen:
                if p["type"] == "annual":
                    p["fiscal_year"] = _anchor_year(p["end"]) + year_offset
        chosen_by_metric.append((metric, chosen))

    # Pass 2: label everything on one company calendar, then output rows + derived quarters
    calendar = _fiscal_calendar(chosen_by_metric)
    for metric, chosen in chosen_by_metric:
        _relabel(chosen, calendar)
        base = {"cik": cik, "ticker": ticker, "metric": metric.key, "unit": metric.unit}
        seen: set[tuple] = set()  # (fiscal_year, fiscal_period) already output
        for p in chosen:
            if p["type"] not in ROW_PERIOD_TYPES:
                continue  # YTD figures are inputs for derived quarters, not rows
            label = (p["fiscal_year"], p["fiscal_period"])
            if label in seen:
                continue  # two filings' versions of one period (dates a few days apart)
            seen.add(label)
            rows.append(
                {
                    **base,
                    "value": p["value"],
                    "fiscal_year": p["fiscal_year"],
                    "fiscal_period": p["fiscal_period"],
                    "period_end": p["end"],
                    "form": p["form"],
                    "filed_date": p["filed"],
                    "accession_no": p["accn"],
                }
            )

        if metric.kind == "flow":
            for q in _derive_quarters(metric, chosen):
                label = (q["fiscal_year"], q["fiscal_period"])
                if label in seen:
                    continue  # already reported, or derived from an overlapping year
                seen.add(label)
                rows.append({**base, **q, "form": DERIVED_FORM, "accession_no": None})

    rows.extend(_free_cash_flow(rows))
    return rows
