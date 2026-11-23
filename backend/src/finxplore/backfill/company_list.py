"""Build data/config/sp500_ciks.csv: the S&P 500 company list with sector and exchange.

Sources:
- Wikipedia "List of S&P 500 companies" (constituents table): ticker, name, GICS sector, CIK
- SEC company_tickers_exchange.json: exchange (via SecClient, so the SEC User-Agent rule applies)

Companies with several share classes (GOOGL/GOOG, FOXA/FOX, NWSA/NWS) appear once, under the
first ticker listed, because facts are reported per company (CIK), not per share class.

Usage (from backend/, venv active):
    python -m finxplore.backfill.company_list --out ../data/config/sp500_ciks.csv
SEC_USER_AGENT is read from the environment or from the repo-root .env file.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
from html.parser import HTMLParser
from pathlib import Path

import requests

from finxplore.sec.client import pad_cik

WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
SEC_TICKERS_EXCHANGE_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
# Generic client name only: the SEC contact email is sent to the SEC alone, never to Wikipedia.
WIKIPEDIA_USER_AGENT = "FinXplore/0.1 (educational S&P 500 list builder)"
FIELDS = ["cik", "ticker", "name", "sector", "exchange"]
SHARE_CLASS_SUFFIX = re.compile(r"\s*\(Class [A-Z]\)$")


class _ConstituentsTableParser(HTMLParser):
    """Collect the text of every cell in <table id="constituents">, row by row."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._table_depth = 0  # >0 while inside the constituents table (handles nested tables)
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            if self._table_depth or dict(attrs).get("id") == "constituents":
                self._table_depth += 1
            return
        if self._table_depth != 1:
            return
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self._table_depth:
            self._table_depth -= 1
        elif self._table_depth != 1:
            return
        elif tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def parse_constituents(html: str) -> list[dict[str, str]]:
    """Return one dict per company (cik, ticker, name, sector) from the Wikipedia page HTML."""
    parser = _ConstituentsTableParser()
    parser.feed(html)
    if not parser.rows:
        raise ValueError("constituents table not found; the Wikipedia page layout may have changed")

    header, *body = parser.rows
    col = {name.lower(): i for i, name in enumerate(header)}
    try:
        i_ticker, i_name = col["symbol"], col["security"]
        i_sector, i_cik = col["gics sector"], col["cik"]
    except KeyError as e:
        raise ValueError(f"unexpected constituents table header: {header}") from e

    companies: dict[str, dict[str, str]] = {}
    for row in body:
        if len(row) <= max(i_ticker, i_name, i_sector, i_cik):
            continue
        cik = pad_cik(row[i_cik])
        companies.setdefault(  # first share class wins
            cik,
            {
                "cik": cik,
                "ticker": row[i_ticker],
                "name": SHARE_CLASS_SUFFIX.sub("", row[i_name]),
                "sector": row[i_sector],
            },
        )
    return list(companies.values())


def exchanges_by_cik(sec_json: dict) -> dict[str, str]:
    """Map padded CIK -> exchange from the SEC company_tickers_exchange.json payload."""
    fields = sec_json["fields"]
    i_cik, i_exchange = fields.index("cik"), fields.index("exchange")
    result: dict[str, str] = {}
    for row in sec_json["data"]:
        if row[i_exchange]:
            result.setdefault(pad_cik(row[i_cik]), row[i_exchange])
    return result


def build_company_list(html: str, sec_json: dict) -> list[dict[str, str]]:
    exchanges = exchanges_by_cik(sec_json)
    companies = parse_constituents(html)
    for c in companies:
        c["exchange"] = exchanges.get(c["cik"], "")
    return sorted(companies, key=lambda c: c["ticker"])


def _load_dotenv(path: Path) -> None:
    """Minimal .env reader so local runs pick up SEC_USER_AGENT. Never overrides real env vars."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--out", type=Path, required=True, help="CSV path to write")
    args = parser.parse_args()

    _load_dotenv(Path(__file__).resolve().parents[4] / ".env")
    from finxplore.sec.client import SecClient  # after .env is loaded (settings are cached)

    resp = requests.get(WIKIPEDIA_URL, headers={"User-Agent": WIKIPEDIA_USER_AGENT}, timeout=30)
    resp.raise_for_status()
    sec_json = SecClient().get_json(SEC_TICKERS_EXCHANGE_URL)

    companies = build_company_list(resp.text, sec_json)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(companies)

    missing_exchange = [c["ticker"] for c in companies if not c["exchange"]]
    sectors = sorted({c["sector"] for c in companies})
    print(f"wrote {len(companies)} companies to {args.out}")
    print(f"{len(sectors)} sectors: {', '.join(sectors)}")
    if missing_exchange:
        print(f"no exchange found for: {', '.join(missing_exchange)}")


if __name__ == "__main__":
    main()
