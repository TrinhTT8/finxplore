"""Validate model-generated SQL before it ever reaches Athena (FR-14, AI design step 4).

Rules:
- exactly one statement, and it must be a SELECT (CTEs allowed)
- only the `facts` and `companies` tables (and CTEs defined in the query)
- only known columns (or aliases defined in the query)
- always LIMIT <= max_rows (added if missing, lowered if too high)

Anything else raises UnsafeSQLError. This is defense in depth: the Athena workgroup
is read-only and scan-limited as well.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

DIALECT = "trino"  # Athena engine v3 is Trino-based

ALLOWED_COLUMNS: dict[str, set[str]] = {
    "facts": {
        "cik",
        "ticker",
        "metric",
        "value",
        "unit",
        "fiscal_year",
        "fiscal_period",
        "period_end",
        "form",
        "filed_date",
        "accession_no",
    },
    "companies": {"cik", "ticker", "name", "sector", "exchange"},
}

FORBIDDEN_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.Command,
    exp.TruncateTable,
)


class UnsafeSQLError(ValueError):
    """Raised when generated SQL breaks a safety rule."""


def validate_sql(sql: str, max_rows: int = 100, database: str | None = None) -> str:
    """Return a safe, normalized SQL string or raise UnsafeSQLError."""
    try:
        statements = [s for s in sqlglot.parse(sql, read=DIALECT) if s is not None]
    except ParseError as e:
        raise UnsafeSQLError(f"could not parse SQL: {e}") from e

    if len(statements) != 1:
        raise UnsafeSQLError("exactly one statement is allowed")
    stmt = statements[0]

    if not isinstance(stmt, exp.Select):
        raise UnsafeSQLError("only SELECT statements are allowed")
    if stmt.find(*FORBIDDEN_NODES):
        raise UnsafeSQLError("write or DDL operations are not allowed")

    cte_names = {cte.alias_or_name.lower() for cte in stmt.find_all(exp.CTE)}
    aliases = {a.alias.lower() for a in stmt.find_all(exp.Alias)} | {
        t.alias.lower() for t in stmt.find_all(exp.Table) if t.alias
    }

    for table in stmt.find_all(exp.Table):
        name = table.name.lower()
        if name in cte_names:
            continue
        if name not in ALLOWED_COLUMNS:
            raise UnsafeSQLError(f"table not allowed: {name}")
        if table.db and (database is None or table.db.lower() != database.lower()):
            raise UnsafeSQLError(f"database not allowed: {table.db}")
        if table.catalog:
            raise UnsafeSQLError("catalog-qualified tables are not allowed")

    allowed_cols = set().union(*ALLOWED_COLUMNS.values()) | aliases
    for col in stmt.find_all(exp.Column):
        if isinstance(col.this, exp.Star):
            continue
        if col.name.lower() not in allowed_cols:
            raise UnsafeSQLError(f"column not allowed: {col.name}")

    limit = stmt.args.get("limit")
    current = None
    if limit is not None:
        value = limit.expression
        if isinstance(value, exp.Literal) and value.is_int:
            current = int(value.this)
    if current is None or current > max_rows:
        stmt = stmt.limit(max_rows)

    return stmt.sql(dialect=DIALECT)
