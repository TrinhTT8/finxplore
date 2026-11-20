"""Core metric definitions and XBRL tag fallback mapping (FR-2, FR-7).

Companies report the same concept under different us-gaap tags. Each metric lists
its tags in priority order; for every period, the first tag that has a value wins.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# flow    = measured over a period (income statement, cash flow); quarters sum to the year,
#           so Q4 can be derived as FY - Q1 - Q2 - Q3.
# instant = measured at a point in time (balance sheet).
# ratio   = per-share / averaged values that must not be summed.
Kind = Literal["flow", "instant", "ratio"]


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    unit: str  # unit key inside companyfacts "units", e.g. "USD", "USD/shares", "shares"
    kind: Kind
    tags: tuple[str, ...]


CORE_METRICS: tuple[Metric, ...] = (
    Metric(
        "revenue",
        "Revenue (sales)",
        "USD",
        "flow",
        (
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
            "SalesRevenueNet",
        ),
    ),
    Metric("gross_profit", "Gross profit", "USD", "flow", ("GrossProfit",)),
    Metric("operating_income", "Operating income", "USD", "flow", ("OperatingIncomeLoss",)),
    Metric("net_income", "Net income (profit)", "USD", "flow", ("NetIncomeLoss", "ProfitLoss")),
    Metric(
        "rnd_expense", "Research & development", "USD", "flow", ("ResearchAndDevelopmentExpense",)
    ),
    Metric(
        "eps_diluted",
        "Earnings per share",
        "USD/shares",
        "ratio",
        ("EarningsPerShareDiluted", "EarningsPerShareBasic"),
    ),
    Metric(
        "shares_diluted",
        "Shares outstanding (diluted)",
        "shares",
        "ratio",
        ("WeightedAverageNumberOfDilutedSharesOutstanding",),
    ),
    Metric(
        "operating_cash_flow",
        "Operating cash flow",
        "USD",
        "flow",
        ("NetCashProvidedByUsedInOperatingActivities",),
    ),
    Metric(
        "capex",
        "Capital expenditures",
        "USD",
        "flow",
        ("PaymentsToAcquirePropertyPlantAndEquipment",),
    ),
    Metric(
        "dividends_paid",
        "Dividends paid",
        "USD",
        "flow",
        ("PaymentsOfDividends", "PaymentsOfDividendsCommonStock"),
    ),
    Metric("total_assets", "Total assets", "USD", "instant", ("Assets",)),
    Metric("total_liabilities", "Total liabilities", "USD", "instant", ("Liabilities",)),
    Metric(
        "stockholders_equity",
        "Shareholders' equity",
        "USD",
        "instant",
        (
            "StockholdersEquity",
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        ),
    ),
    Metric(
        "cash",
        "Cash and equivalents",
        "USD",
        "instant",
        (
            "CashAndCashEquivalentsAtCarryingValue",
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        ),
    ),
    Metric(
        "long_term_debt",
        "Long-term debt",
        "USD",
        "instant",
        ("LongTermDebtNoncurrent", "LongTermDebt"),
    ),
)

# Derived metrics are computed after extraction:
#   free_cash_flow = operating_cash_flow - capex
DERIVED_METRICS = ("free_cash_flow",)

METRICS_BY_KEY = {m.key: m for m in CORE_METRICS}
