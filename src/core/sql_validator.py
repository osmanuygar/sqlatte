"""
SQL query validator – enforces SELECT-only access.
Strips string literals and comments before analysis to avoid false positives.
"""
import re

_SAFE_ID = re.compile(r'^[a-zA-Z0-9_][a-zA-Z0-9_.]{0,127}$')


def validate_identifier(name: str) -> str:
    """Validate a SQL identifier (table/schema name) to prevent injection.

    Allows letters, digits, underscores, and dots (for catalog.schema.table).
    Raises ValueError for anything else.
    """
    if not _SAFE_ID.match(name):
        raise ValueError(f"Invalid identifier: {name!r}")
    return name

_DANGEROUS = re.compile(
    r'\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE|'
    r'EXEC|EXECUTE|CALL|MERGE|REPLACE|LOAD|COPY|IMPORT|ATTACH|DETACH|'
    r'RENAME|LOCK|UNLOCK|SET|INTO)\b',
    re.IGNORECASE,
)


def _strip_sql(sql: str) -> str:
    """Remove string literals and comments so keyword checks are reliable."""
    sql = re.sub(r"'[^']*'", "''", sql)
    sql = re.sub(r'"[^"]*"', '""', sql)
    sql = re.sub(r'--[^\n]*', '', sql)
    sql = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)
    return sql.strip()


def is_select_only(sql: str) -> bool:
    """Return True only for read-only SELECT / WITH…SELECT queries."""
    clean = _strip_sql(sql)
    if not clean:
        return False
    first_word = clean.split()[0].upper()
    if first_word not in ('SELECT', 'WITH'):
        return False
    return not bool(_DANGEROUS.search(clean))


def violation_reason(sql: str) -> str:
    """Human-readable reason a query was rejected."""
    clean = _strip_sql(sql)
    if not clean:
        return "Empty query"
    first_word = clean.split()[0].upper()
    if first_word not in ('SELECT', 'WITH'):
        return f"Query starts with '{first_word}' — only SELECT statements are permitted"
    m = _DANGEROUS.search(clean)
    if m:
        return f"Query contains forbidden keyword '{m.group().upper()}'"
    return "Query is not a read-only SELECT statement"
