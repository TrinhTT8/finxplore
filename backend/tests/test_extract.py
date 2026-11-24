import json
from pathlib import Path

from finxplore.pipeline.extract import extract_facts, merge_companyfacts

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
    # Both tags report FY2023; the higher-priority tag (Revenues, the total) wins.
    # The fixture's Revenues value is a made-up round 400B so it is obvious which tag was used
    # (it must stay above half of contract revenue, or the component floor would reject it).
    fy2023 = [r for r in _rows("revenue") if r["period_end"] == "2023-09-30"]
    assert [r["value"] for r in fy2023] == [400000000000]


def test_skips_ytd_periods_and_keeps_quarters():
    periods = {r["fiscal_period"] for r in _rows("revenue")}
    assert periods == {"FY", "Q1"}  # the 6-month YTD fact is skipped


def test_instant_metric():
    assets = _rows("total_assets")
    assert len(assets) == 1
    assert assets[0]["value"] == 352583000000


def _revenue_fact(start, end, val, filed, fy, fp, form="10-K"):
    return {
        "start": start,
        "end": end,
        "val": val,
        "filed": filed,
        "fy": fy,
        "fp": fp,
        "form": form,
        "accn": f"acc-{filed}",
    }


def test_merge_companyfacts_pools_history_and_latest_filed_wins():
    old = {
        "cik": 34088,
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "label": "Revenues",
                    "units": {
                        "USD": [
                            _revenue_fact(
                                "2024-01-01", "2024-12-31", 100, "2025-02-01", 2024, "FY"
                            ),
                            _revenue_fact(
                                "2025-01-01", "2025-12-31", 200, "2026-02-01", 2025, "FY"
                            ),
                        ]
                    },
                }
            }
        },
    }
    new = {
        "cik": 2115436,
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "label": "Revenues",
                    "units": {
                        "USD": [
                            # New registrant re-reports FY2025 later with a restated value
                            _revenue_fact(
                                "2025-01-01", "2025-12-31", 210, "2027-02-01", 2026, "FY"
                            ),
                        ]
                    },
                }
            }
        },
    }

    merged = merge_companyfacts(new, [old])
    rows = {
        r["period_end"]: r for r in extract_facts(merged, ticker="XOM") if r["metric"] == "revenue"
    }

    assert merged["cik"] == 2115436
    assert len(new["facts"]["us-gaap"]["Revenues"]["units"]["USD"]) == 1  # input not mutated
    assert rows["2024-12-31"]["value"] == 100  # history only the predecessor has
    assert rows["2025-12-31"]["value"] == 210  # latest-filed value wins
    assert rows["2025-12-31"]["fiscal_year"] == 2025  # label from the earliest filing
    assert {r["cik"] for r in rows.values()} == {"0002115436"}


def test_revenues_total_beats_contract_revenue_subset():
    # Regression: Berkshire Hathaway reports both tags. Contract revenue ($247B) excludes
    # insurance premiums and investment income; Revenues ($371B) is the total we want.
    fy2025 = ("2025-01-01", "2025-12-31")
    berkshire = {
        "cik": 1067983,
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {"USD": [_revenue_fact(*fy2025, 247, "2026-03-02", 2025, "FY")]}
                },
                "Revenues": {
                    "units": {"USD": [_revenue_fact(*fy2025, 371, "2026-03-02", 2025, "FY")]}
                },
            }
        },
    }

    revenue = [r for r in extract_facts(berkshire, ticker="BRK.B") if r["metric"] == "revenue"]

    assert len(revenue) == 1
    assert revenue[0]["value"] == 371


def _doc(cik: int, **tags: list[dict]) -> dict:
    """A minimal companyfacts document: tag name -> list of USD facts."""
    return {"cik": cik, "facts": {"us-gaap": {t: {"units": {"USD": f}} for t, f in tags.items()}}}


def _revenue(doc: dict) -> list[dict]:
    return [r for r in extract_facts(doc, ticker="T") if r["metric"] == "revenue"]


FY2019 = ("2018-05-28", "2019-05-26")
CONTRACT = "RevenueFromContractWithCustomerExcludingAssessedTax"


def test_revenues_tag_used_for_one_stream_is_rejected():
    # Regression: General Mills / Eaton / Emerson tag a single revenue stream as `Revenues`.
    # A total cannot be under half of one of its parts, so fall back to contract revenue.
    doc = _doc(
        40704,
        Revenues=[_revenue_fact(*FY2019, 4.7e9, "2019-06-28", 2019, "FY")],
        **{CONTRACT: [_revenue_fact(*FY2019, 16.9e9, "2019-06-28", 2019, "FY")]},
    )
    assert [r["value"] for r in _revenue(doc)] == [16.9e9]


def test_revenues_of_zero_is_rejected():
    doc = _doc(
        1551182,
        Revenues=[_revenue_fact(*FY2019, 0, "2019-06-28", 2019, "FY")],
        **{CONTRACT: [_revenue_fact(*FY2019, 19.7e9, "2019-06-28", 2019, "FY")]},
    )
    assert [r["value"] for r in _revenue(doc)] == [19.7e9]


def test_revenues_moderately_below_contract_is_kept():
    # Williams / EQT: total revenue after hedging losses is below gross contract revenue.
    # That is a real total (above the 50% floor), so Revenues still wins.
    doc = _doc(
        107263,
        Revenues=[_revenue_fact(*FY2019, 10.5e9, "2019-06-28", 2019, "FY")],
        **{CONTRACT: [_revenue_fact(*FY2019, 12.6e9, "2019-06-28", 2019, "FY")]},
    )
    assert [r["value"] for r in _revenue(doc)] == [10.5e9]


def test_tax_inclusive_revenue_does_not_reject_net_revenues():
    # Tobacco: revenue including excise tax can be ~2x net revenue. The tax-inclusive tag is
    # not a component of Revenues, so it must not trigger the floor.
    doc = _doc(
        1413329,
        Revenues=[_revenue_fact(*FY2019, 37.9e9, "2019-06-28", 2019, "FY")],
        RevenueFromContractWithCustomerIncludingAssessedTax=[
            _revenue_fact(*FY2019, 88.0e9, "2019-06-28", 2019, "FY")
        ],
    )
    assert [r["value"] for r in _revenue(doc)] == [37.9e9]


def test_q4_quarter_in_a_10k_is_labelled_q4_not_fy():
    # Regression: a 10-K contains the 3-month Q4 figures and its `fp` is "FY", which used to
    # produce two "FY" rows for the same period end (Abbott: $35.2B year and $10.0B quarter).
    doc = _doc(
        1800,
        Revenues=[
            _revenue_fact("2010-01-01", "2010-12-31", 35.2e9, "2011-02-18", 2010, "FY"),
            _revenue_fact("2010-10-01", "2010-12-31", 10.0e9, "2011-02-18", 2010, "FY"),
        ],
    )
    rows = {r["fiscal_period"]: r for r in _revenue(doc)}
    assert set(rows) == {"FY", "Q4"}
    assert rows["FY"]["value"] == 35.2e9
    assert rows["Q4"]["value"] == 10.0e9
    assert rows["Q4"]["fiscal_year"] == 2010


def test_comparative_first_seen_a_year_later_gets_its_own_fiscal_year():
    # 2008 figures first appear in the 2009 10-K (the company's first XBRL filing, fy=2009).
    doc = _doc(
        1800,
        Revenues=[
            _revenue_fact("2008-01-01", "2008-12-31", 29.5e9, "2010-02-19", 2009, "FY"),
            _revenue_fact("2008-10-01", "2008-12-31", 7.9e9, "2010-02-19", 2009, "FY"),
        ],
    )
    rows = {r["fiscal_period"]: r for r in _revenue(doc)}
    assert rows["FY"]["fiscal_year"] == 2008
    assert rows["Q4"]["fiscal_year"] == 2008


def test_quarters_from_10q_keep_their_label():
    # Apple-style fiscal year: Q1 FY2023 ends in December 2022.
    doc = _doc(
        320193,
        Revenues=[
            _revenue_fact("2022-09-25", "2022-12-31", 117.2e9, "2023-02-03", 2023, "Q1", "10-Q")
        ],
    )
    [row] = _revenue(doc)
    assert (row["fiscal_period"], row["fiscal_year"]) == ("Q1", 2023)


def test_start_dates_a_day_apart_are_one_period_and_latest_filed_wins():
    # Regression: Aflac/AIG report the same year as starting 2009-01-01 in one filing and
    # 2008-12-31 in another; that used to produce two FY rows for 2009-12-31.
    doc = _doc(
        4977,
        Revenues=[
            _revenue_fact("2009-01-01", "2009-12-31", 18.0e9, "2010-02-26", 2009, "FY"),
            _revenue_fact("2008-12-31", "2009-12-31", 18.3e9, "2012-02-27", 2011, "FY"),
        ],
    )
    [row] = _revenue(doc)
    assert row["value"] == 18.3e9  # restated value from the later filing
    assert row["fiscal_year"] == 2009  # label from the period's own 10-K


def test_pre_2018_sales_revenue_net_also_guards_against_partial_revenues():
    # Regression: L3Harris FY2010 tagged a $0.1B stream as `Revenues` next to $5.2B of
    # SalesRevenueNet (the pre-2018 name for net sales).
    doc = _doc(
        202058,
        Revenues=[_revenue_fact("2009-07-04", "2010-07-02", 0.102e9, "2012-08-27", 2012, "FY")],
        SalesRevenueNet=[
            _revenue_fact("2009-07-04", "2010-07-02", 5.206e9, "2010-08-30", 2010, "FY")
        ],
    )
    [row] = _revenue(doc)
    assert row["value"] == 5.206e9
    assert row["fiscal_year"] == 2010


def test_override_replaces_tag_list_and_disables_component_floor():
    # BlackRock-style: `Revenues` is a subset (~60% of contract revenue), so the 50% floor
    # cannot catch it. An override names the right tag for this company.
    doc = _doc(
        2012383,
        Revenues=[_revenue_fact(*FY2019, 12.8e9, "2019-06-28", 2019, "FY")],
        **{CONTRACT: [_revenue_fact(*FY2019, 20.4e9, "2019-06-28", 2019, "FY")]},
    )
    assert [r["value"] for r in _revenue(doc)] == [12.8e9]  # default rules

    rows = extract_facts(doc, ticker="BLK", overrides={"revenue": (CONTRACT,)})
    assert [r["value"] for r in rows if r["metric"] == "revenue"] == [20.4e9]


def test_override_only_listed_tags_are_used():
    # Philip Morris-style: only the net tag is allowed; a year without it is left out
    # rather than filled with a tax-inclusive (wrong) value.
    doc = _doc(
        1413329,
        SalesRevenueNet=[_revenue_fact(*FY2019, 80.1e9, "2019-06-28", 2019, "FY")],
    )
    rows = extract_facts(doc, ticker="PM", overrides={"revenue": (CONTRACT,)})
    assert [r for r in rows if r["metric"] == "revenue"] == []


def test_override_for_one_metric_leaves_others_alone():
    doc = _load()
    default = [r for r in extract_facts(doc, ticker="AAPL") if r["metric"] != "revenue"]
    overridden = extract_facts(doc, ticker="AAPL", overrides={"revenue": ("SalesRevenueNet",)})
    assert [r for r in overridden if r["metric"] != "revenue"] == default
