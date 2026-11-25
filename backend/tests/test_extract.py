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


def test_ytd_is_not_a_row_but_derives_the_missing_quarter():
    rows = {r["fiscal_period"]: r for r in _rows("revenue") if r["fiscal_year"] == 2023}
    assert set(rows) == {"FY", "Q1", "Q2"}  # no 6-month row; Q2 is calculated from it
    q2 = rows["Q2"]
    assert q2["value"] == 211990000000 - 117154000000  # 6-month YTD - Q1 = Apple's real Q2
    assert (q2["form"], q2["accession_no"], q2["period_end"]) == ("derived", None, "2023-04-01")
    assert rows["Q1"]["form"] == "10-Q"  # reported quarters are untouched


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


# ---------- Derived quarters and free cash flow ----------
FY24 = ("2024-01-01", "2024-12-31")


def _flow(start, end, val, filed, fp, form):
    return _revenue_fact(start, end, val, filed, 2024, fp, form)


def _cash_flow_year(q1: float, h1: float, nine: float, year: float) -> list[dict]:
    """How 10-Qs report cash flow: Q1, then 6- and 9-month year-to-date, then the 10-K year."""
    return [
        _flow("2024-01-01", "2024-03-31", q1, "2024-05-01", "Q1", "10-Q"),
        _flow("2024-01-01", "2024-06-30", h1, "2024-08-01", "Q2", "10-Q"),
        _flow("2024-01-01", "2024-09-30", nine, "2024-11-01", "Q3", "10-Q"),
        _flow(*FY24, year, "2025-02-15", "FY", "10-K"),
    ]


def _by_period(rows, metric):
    return {r["fiscal_period"]: r for r in rows if r["metric"] == metric}


def test_cash_flow_quarters_are_derived_from_year_to_date():
    doc = _doc(
        1,
        NetCashProvidedByUsedInOperatingActivities=_cash_flow_year(10, 25, 45, 70),
    )
    ocf = _by_period(extract_facts(doc), "operating_cash_flow")
    assert {k: r["value"] for k, r in ocf.items()} == {
        "Q1": 10,
        "Q2": 15,
        "Q3": 20,
        "Q4": 25,
        "FY": 70,
    }
    assert [ocf[k]["form"] for k in ("Q1", "Q2", "Q3", "Q4", "FY")] == [
        "10-Q",
        "derived",
        "derived",
        "derived",
        "10-K",
    ]
    assert [ocf[k]["period_end"] for k in ("Q2", "Q3", "Q4")] == [
        "2024-06-30",
        "2024-09-30",
        "2024-12-31",
    ]
    assert {r["fiscal_year"] for r in ocf.values()} == {2024}
    assert ocf["Q4"]["filed_date"] == "2025-02-15"  # latest filing used in the calculation


def test_q4_falls_back_to_year_minus_reported_quarters():
    # Income statements: 10-Qs report 3-month quarters, the 10-K only the full year.
    doc = _doc(
        2,
        Revenues=[
            _flow("2024-01-01", "2024-03-31", 100, "2024-05-01", "Q1", "10-Q"),
            _flow("2024-04-01", "2024-06-30", 110, "2024-08-01", "Q2", "10-Q"),
            _flow("2024-07-01", "2024-09-30", 120, "2024-11-01", "Q3", "10-Q"),
            _flow(*FY24, 460, "2025-02-15", "FY", "10-K"),
        ],
    )
    revenue = _by_period(extract_facts(doc), "revenue")
    assert revenue["Q4"]["value"] == 460 - 100 - 110 - 120
    assert revenue["Q4"]["form"] == "derived"


def test_reported_q4_is_never_replaced():
    doc = _doc(
        3,
        Revenues=[
            _flow("2024-01-01", "2024-03-31", 100, "2024-05-01", "Q1", "10-Q"),
            _flow("2024-04-01", "2024-06-30", 110, "2024-08-01", "Q2", "10-Q"),
            _flow("2024-07-01", "2024-09-30", 120, "2024-11-01", "Q3", "10-Q"),
            _flow("2024-10-01", "2024-12-31", 131, "2025-02-15", "FY", "10-K"),  # real Q4
            _flow(*FY24, 460, "2025-02-15", "FY", "10-K"),
        ],
    )
    q4 = [r for r in extract_facts(doc) if r["metric"] == "revenue" and r["fiscal_period"] == "Q4"]
    assert [(r["value"], r["form"]) for r in q4] == [(131, "10-K")]


def test_impossible_derived_quarters_are_dropped():
    # A restated (smaller) year next to unrestated quarters gives a negative Q4: not stored.
    negative = _doc(
        4,
        Revenues=[
            _flow("2024-01-01", "2024-09-30", 300, "2024-11-01", "Q3", "10-Q"),
            _flow(*FY24, 250, "2025-02-15", "FY", "10-K"),
        ],
    )
    assert "Q4" not in _by_period(extract_facts(negative), "revenue")

    # Signed metrics (net income) may have a loss quarter bigger than the yearly profit.
    loss = _doc(
        5,
        NetIncomeLoss=[
            _flow("2024-01-01", "2024-09-30", 300, "2024-11-01", "Q3", "10-Q"),
            _flow(*FY24, 250, "2025-02-15", "FY", "10-K"),
        ],
    )
    assert _by_period(extract_facts(loss), "net_income")["Q4"]["value"] == -50


def test_ratio_metrics_are_not_derived():
    doc = _doc(6)
    doc["facts"]["us-gaap"]["EarningsPerShareDiluted"] = {
        "units": {
            "USD/shares": [
                _flow("2024-01-01", "2024-09-30", 3.0, "2024-11-01", "Q3", "10-Q"),
                _flow(*FY24, 4.1, "2025-02-15", "FY", "10-K"),
            ]
        }
    }
    eps = _by_period(extract_facts(doc), "eps_diluted")
    assert set(eps) == {"FY"}  # per-share values can't be subtracted (share count changes)


def test_free_cash_flow_for_every_period_with_both_inputs():
    doc = _doc(
        7,
        NetCashProvidedByUsedInOperatingActivities=_cash_flow_year(10, 25, 45, 70),
        PaymentsToAcquirePropertyPlantAndEquipment=_cash_flow_year(3, 7, 12, 20),
    )
    fcf = _by_period(extract_facts(doc), "free_cash_flow")
    assert {k: r["value"] for k, r in fcf.items()} == {
        "Q1": 10 - 3,
        "Q2": 15 - 4,
        "Q3": 20 - 5,
        "Q4": 25 - 8,
        "FY": 70 - 20,
    }
    assert {r["form"] for r in fcf.values()} == {"derived"}
    assert {r["unit"] for r in fcf.values()} == {"USD"}


def test_quarter_from_10k_quarterly_table_is_labelled_by_its_dates():
    # Regression: Apple's 10-K quarterly table (fp=FY, fy=2017) re-reported the quarter
    # ending 2016-12-31 under a tag its 10-Q didn't use, so it was labelled "Q4 FY2017".
    # By dates it is Q1 of the fiscal year 2016-09-25..2017-09-30.
    doc = _doc(
        320193,
        Revenues=[
            _revenue_fact("2016-09-25", "2016-12-31", 78.4e9, "2017-11-03", 2017, "FY"),
            _revenue_fact("2016-09-25", "2017-09-30", 229.2e9, "2017-11-03", 2017, "FY"),
        ],
    )
    q = [r for r in _revenue(doc) if r["period_end"] == "2016-12-31"]
    assert [(r["fiscal_year"], r["fiscal_period"]) for r in q] == [(2017, "Q1")]


def test_overlapping_fiscal_years_do_not_duplicate_derived_quarters():
    # Regression (Ciena): two annual periods a few days apart for the same year used to
    # derive the same quarter twice.
    doc = _doc(
        936395,
        NetCashProvidedByUsedInOperatingActivities=[
            *_cash_flow_year(10, 25, 45, 70),
            _flow("2024-01-01", "2024-12-28", 70, "2025-03-01", "FY", "10-K"),
        ],
    )
    q2 = [
        r
        for r in extract_facts(doc)
        if r["metric"] == "operating_cash_flow" and r["fiscal_period"] == "Q2"
    ]
    assert len(q2) == 1


# ---------- Fiscal year naming convention ----------
def _annual(start, end, val, filed, fy):
    return _revenue_fact(start, end, val, filed, fy, "FY")


def test_wrong_fy_in_one_filing_does_not_duplicate_a_year():
    # Regression (Arch Capital): the 10-K for 2021 carried fy=2020, so two different years
    # were both labelled "FY 2020". The company's convention (offset 0) is applied instead.
    doc = _doc(
        947484,
        Revenues=[
            _annual("2019-01-01", "2019-12-31", 7.0e9, "2020-02-28", 2019),
            _annual("2020-01-01", "2020-12-31", 8.5e9, "2021-02-26", 2020),
            _annual("2021-01-01", "2021-12-31", 9.2e9, "2022-02-25", 2020),  # bad fy
            _annual("2022-01-01", "2022-12-31", 10.1e9, "2023-02-24", 2022),
        ],
    )
    years = {r["period_end"]: r["fiscal_year"] for r in _revenue(doc)}
    assert years == {"2019-12-31": 2019, "2020-12-31": 2020, "2021-12-31": 2021, "2022-12-31": 2022}


def test_53_week_year_ending_in_early_january_keeps_its_name():
    # Snap-on style: fiscal 2025 ended 2026-01-03, fiscal 2024 ended 2024-12-28.
    doc = _doc(
        91440,
        Revenues=[
            _annual("2023-12-31", "2024-12-28", 4.7e9, "2025-02-13", 2024),
            _annual("2024-12-29", "2026-01-03", 4.8e9, "2026-02-12", 2025),
        ],
    )
    years = {r["period_end"]: r["fiscal_year"] for r in _revenue(doc)}
    assert years == {"2024-12-28": 2024, "2026-01-03": 2025}


def test_company_naming_year_before_its_end_date_is_respected():
    # Target style: the year ending 2026-01-31 is "fiscal 2025" (offset -1); its quarters
    # follow the annual period's year.
    doc = _doc(
        27419,
        Revenues=[
            _annual("2024-02-04", "2025-02-01", 106.6e9, "2025-03-12", 2024),
            _annual("2025-02-02", "2026-01-31", 104.0e9, "2026-03-11", 2025),
            _revenue_fact("2025-02-02", "2025-05-03", 23.8e9, "2025-05-28", 2025, "Q1", "10-Q"),
        ],
    )
    labels = {r["period_end"]: (r["fiscal_year"], r["fiscal_period"]) for r in _revenue(doc)}
    assert labels["2026-01-31"] == (2025, "FY")
    assert labels["2025-02-01"] == (2024, "FY")
    assert labels["2025-05-03"] == (2025, "Q1")


def test_balance_sheet_dates_are_labelled_on_the_company_calendar():
    # Regression (Agilent, fiscal year ends Oct 31): the 10-K's prior-year balance and the
    # 10-Q's Q1 balance were both labelled "Q1 2019". By the calendar, 2018-10-31 is the end
    # of FY2018 and 2019-01-31 is Q1 of FY2019.
    doc = _doc(
        1090872,
        Revenues=[
            _annual("2017-11-01", "2018-10-31", 4.9e9, "2018-12-20", 2018),
            _annual("2018-11-01", "2019-10-31", 5.2e9, "2019-12-19", 2019),
        ],
        CashAndCashEquivalentsAtCarryingValue=[
            {"end": "2018-10-31", "val": 2.2e9, "accn": "a", "fy": 2019, "fp": "Q1",
             "form": "10-Q", "filed": "2019-03-01"},
            {"end": "2019-01-31", "val": 2.0e9, "accn": "b", "fy": 2019, "fp": "Q1",
             "form": "10-Q", "filed": "2019-03-01"},
        ],
    )  # fmt: skip
    cash = {r["period_end"]: (r["fiscal_year"], r["fiscal_period"])
            for r in extract_facts(doc) if r["metric"] == "cash"}  # fmt: skip
    assert cash == {"2018-10-31": (2018, "FY"), "2019-01-31": (2019, "Q1")}


def test_trailing_twelve_months_in_a_10q_is_not_a_fiscal_year():
    # Regression (Amazon): 10-Qs include 12-month figures ending at the quarter. They are
    # 365 days long but are not fiscal years, and one replaced Amazon's real FY2025.
    doc = _doc(
        1018724,
        NetIncomeLoss=[
            _annual("2024-04-01", "2025-03-31", 65.9e9, "2025-05-02", 2025) | {"form": "10-Q"},
            _annual("2025-01-01", "2025-12-31", 77.7e9, "2026-02-06", 2025),
        ],
    )
    fy = [
        r for r in extract_facts(doc) if r["metric"] == "net_income" and r["fiscal_period"] == "FY"
    ]
    assert [(r["period_end"], r["value"]) for r in fy] == [("2025-12-31", 77.7e9)]
