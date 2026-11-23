import pytest

from finxplore.backfill.company_list import build_company_list, parse_constituents

# Trimmed copy of the Wikipedia constituents table: links, a nested table, and two share classes.
HTML = """
<html><body>
<table id="other"><tr><th>Symbol</th></tr><tr><td>NOPE</td></tr></table>
<table class="wikitable sortable" id="constituents">
<tbody>
<tr><th>Symbol</th><th>Security</th><th>GICS Sector</th><th>GICS Sub-Industry</th>
    <th>Headquarters Location</th><th>Date added</th><th>CIK</th><th>Founded</th></tr>
<tr><td><a href="#">AAPL</a></td><td><a href="#">Apple Inc.</a></td>
    <td>Information Technology</td><td>Technology Hardware</td><td>Cupertino</td>
    <td>1982-11-30</td><td>0000320193</td><td>1977</td></tr>
<tr><td><a href="#">GOOGL</a></td><td>Alphabet Inc. (Class A)</td>
    <td>Communication Services</td><td>Interactive Media</td><td>Mountain View</td>
    <td>2014-04-03</td><td>0001652044</td><td>1998</td></tr>
<tr><td><a href="#">GOOG</a></td><td>Alphabet Inc. (Class C)</td>
    <td>Communication Services</td><td>Interactive Media</td><td>Mountain View</td>
    <td>2006-04-03</td><td>1652044</td><td>1998</td></tr>
<tr><td>BRK.B</td><td>Berkshire Hathaway</td><td>Financials</td>
    <td><table><tr><td>nested</td></tr></table>Multi-Sector Holdings</td><td>Omaha</td>
    <td>2010-02-16</td><td>0001067983</td><td>1839</td></tr>
</tbody>
</table>
</body></html>
"""

SEC_JSON = {
    "fields": ["cik", "name", "ticker", "exchange"],
    "data": [
        [320193, "Apple Inc.", "AAPL", "Nasdaq"],
        [1652044, "Alphabet Inc.", "GOOGL", "Nasdaq"],
        [1652044, "Alphabet Inc.", "GOOG", "Nasdaq"],
        [1067983, "BERKSHIRE HATHAWAY INC", "BRK-B", "NYSE"],
    ],
}


def test_parse_constituents_reads_only_the_constituents_table():
    companies = parse_constituents(HTML)
    assert [c["ticker"] for c in companies] == ["AAPL", "GOOGL", "BRK.B"]
    assert companies[0] == {
        "cik": "0000320193",
        "ticker": "AAPL",
        "name": "Apple Inc.",
        "sector": "Information Technology",
    }


def test_share_classes_collapse_to_one_company_by_cik():
    companies = parse_constituents(HTML)
    alphabet = [c for c in companies if c["cik"] == "0001652044"]
    assert len(alphabet) == 1
    assert alphabet[0]["ticker"] == "GOOGL"
    assert alphabet[0]["name"] == "Alphabet Inc."  # "(Class A)" suffix removed


def test_build_company_list_adds_exchange_and_sorts_by_ticker():
    companies = build_company_list(HTML, SEC_JSON)
    assert [(c["ticker"], c["exchange"]) for c in companies] == [
        ("AAPL", "Nasdaq"),
        ("BRK.B", "NYSE"),
        ("GOOGL", "Nasdaq"),
    ]


def test_missing_table_raises():
    with pytest.raises(ValueError, match="constituents table not found"):
        parse_constituents("<html><table id='x'></table></html>")
