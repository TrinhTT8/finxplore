import pytest

from finxplore.ai.sql_validator import UnsafeSQLError, validate_sql


def test_adds_limit_when_missing():
    sql = validate_sql("SELECT ticker, value FROM facts WHERE metric = 'revenue'")
    assert sql.endswith("LIMIT 100")


def test_lowers_limit_that_is_too_high():
    sql = validate_sql("SELECT ticker FROM facts LIMIT 5000")
    assert "LIMIT 100" in sql
    assert "5000" not in sql


def test_keeps_small_limit():
    assert validate_sql("SELECT ticker FROM facts LIMIT 10").endswith("LIMIT 10")


def test_allows_join_cte_and_aliases():
    sql = """
    WITH rev AS (
        SELECT f.ticker, f.fiscal_year, f.value AS revenue
        FROM facts f WHERE f.metric = 'revenue'
    )
    SELECT c.name, r.fiscal_year, r.revenue
    FROM rev r JOIN companies c ON c.ticker = r.ticker
    ORDER BY revenue DESC
    """
    assert "LIMIT 100" in validate_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE facts",
        "DELETE FROM facts",
        "INSERT INTO facts (cik) VALUES ('1')",
        "SELECT 1; DROP TABLE facts",
        "SELECT * FROM users",
        "SELECT * FROM information_schema.tables",
        "SELECT password FROM facts",
        "CREATE TABLE x AS SELECT * FROM facts",
        "not even sql (",
    ],
)
def test_rejects_unsafe_sql(sql):
    with pytest.raises(UnsafeSQLError):
        validate_sql(sql)
