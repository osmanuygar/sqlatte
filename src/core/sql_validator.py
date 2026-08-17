"""
SQL query validator – enforces SELECT-only access.

Primary check is AST-based (sqlglot): the query is parsed into a real syntax
tree, so keyword/function detection matches actual structure rather than raw
text — immune to comment-splitting or string-escaping tricks that defeat
regex matching. If sqlglot can't fully parse the query (unsupported dialect
syntax, parse error), we fall back to the regex-based checks below rather
than failing open.
"""
import functools
import logging
import re

import sqlglot
from sqlglot import exp

# sqlglot logs a warning and silently degrades to a generic `Command` node for
# syntax it doesn't recognize; we detect that ourselves and fall back, so the
# log noise isn't useful here.
logging.getLogger("sqlglot").setLevel(logging.ERROR)

# Maps SQLatte's `database.provider` config value to a sqlglot dialect name,
# so provider-specific syntax (BigQuery backticks/STRUCT, Trino, …) parses
# correctly instead of spuriously falling back to the regex path.
_PROVIDER_DIALECTS = {
    "trino": "trino",
    "postgresql": "postgres",
    "mysql": "mysql",
    "bigquery": "bigquery",
}


def dialect_for_provider(provider: str) -> str | None:
    """Map a `database.provider` config value to a sqlglot dialect name."""
    return _PROVIDER_DIALECTS.get((provider or "").lower())

_SAFE_ID = re.compile(r'^[a-zA-Z0-9_][a-zA-Z0-9_.]{0,127}$')

# BigQuery job IDs: project:region.jobId — alphanum, underscores, hyphens, one colon, one dot
_SAFE_JOB_ID = re.compile(r'^[a-zA-Z0-9_]([a-zA-Z0-9_\-:.]{0,255})$')


def validate_identifier(name: str) -> str:
    """Validate a SQL identifier (table/schema name) to prevent injection.

    Allows letters, digits, underscores, and dots (for catalog.schema.table).
    Raises ValueError for anything else.
    """
    if not _SAFE_ID.match(name):
        raise ValueError(f"Invalid identifier: {name!r}")
    return name


def validate_job_id(job_id: str) -> str:
    """Validate a BigQuery job ID before embedding in SQL strings.

    Allows alphanumerics, underscores, hyphens, colons and dots — the only
    characters that appear in legitimate BigQuery job IDs.
    Raises ValueError for anything outside this set.
    """
    if not _SAFE_JOB_ID.match(job_id):
        raise ValueError(f"Invalid job_id: {job_id!r}")
    return job_id

_DANGEROUS = re.compile(
    r'\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE|'
    r'EXEC|EXECUTE|CALL|MERGE|REPLACE|LOAD|COPY|IMPORT|ATTACH|DETACH|'
    r'RENAME|LOCK|UNLOCK|SET|INTO)\b',
    re.IGNORECASE,
)

# Dangerous built-in functions that must never appear in queries, even in SELECT.
# Covers PostgreSQL file/system access, MySQL file ops, timing/DoS functions,
# and common data-exfil helpers.
_DANGEROUS_FUNCS = re.compile(
    r'\b('
    # PostgreSQL file/OS access
    r'pg_read_file|pg_read_binary_file|pg_ls_dir|pg_stat_file|'
    r'pg_ls_logdir|pg_ls_waldir|pg_ls_archive_statusdir|'
    r'pg_ls_tmpdir|pg_ls_logicalmapdir|pg_ls_logicalsnapdir|'
    # PostgreSQL code execution / config manipulation
    r'pg_reload_conf|pg_rotate_logfile|pg_terminate_backend|'
    r'pg_cancel_backend|pg_start_backup|pg_stop_backup|'
    # PostgreSQL timing / DoS
    r'pg_sleep|pg_sleep_for|pg_sleep_until|'
    # PostgreSQL large objects (arbitrary read/write)
    r'lo_import|lo_export|lo_creat|lo_create|lo_unlink|'
    # PostgreSQL cross-DB / exfil helpers
    r'dblink|dblink_exec|dblink_connect|dblink_open|'
    r'query_to_xml|query_to_xmlschema|cursor_to_xml|'
    r'pg_copy_to|pg_copy_from|'
    # MySQL file access
    r'load_file|outfile|dumpfile|'
    # Oracle / MSSQL dangerous built-ins
    r'utl_file|utl_http|utl_smtp|utl_tcp|'
    r'xp_cmdshell|xp_regread|sp_execute|'
    # HTTP/DNS exfil functions (various dialects)
    r'http_get|http_post|http_put|http_delete|'
    r'aws_commons|aws_s3|'
    # Generic injection helpers
    r'sys\.exec|sys\.fileio|'
    # BigQuery abuse
    r'EXTERNAL_QUERY'
    r')\s*\(',
    re.IGNORECASE,
)


def _strip_sql(sql: str) -> str:
    """Remove string literals and comments so keyword checks are reliable."""
    sql = re.sub(r"'[^']*'", "''", sql)
    sql = re.sub(r'"[^"]*"', '""', sql)
    sql = re.sub(r'--[^\n]*', '', sql)
    sql = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)
    return sql.strip()


def _regex_is_select_only(sql: str) -> bool:
    """Return True only for read-only SELECT / WITH…SELECT queries."""
    clean = _strip_sql(sql)
    if not clean:
        return False
    first_word = clean.split()[0].upper()
    if first_word not in ('SELECT', 'WITH'):
        return False
    if _DANGEROUS.search(clean):
        return False
    if _DANGEROUS_FUNCS.search(clean):
        return False
    return True


def _regex_violation_reason(sql: str) -> str:
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
    m2 = _DANGEROUS_FUNCS.search(clean)
    if m2:
        return f"Query contains forbidden function '{m2.group().rstrip('(').strip()}'"
    return "Query is not a read-only SELECT statement"


def _regex_risk_score(sql: str) -> int:
    """Return an integer risk score 0–100.

    Scoring is additive and capped at 100.  Lower is safer.

    Base score by statement type
    ─────────────────────────────
      Empty / unparseable query          →  50  (error, not max-risk)
      Non-SELECT / non-WITH statement    →  70  (always blocked by is_select_only)
      SELECT / WITH                      →   0  (read-only baseline)

    Penalty: forbidden write-keywords (each +25, cap at +50)
      Matches from _DANGEROUS (INSERT, DROP, DELETE …)

    Penalty: forbidden dangerous functions (each +40, cap at +80)
      Matches from _DANGEROUS_FUNCS (pg_read_file, dblink, xp_cmdshell …)
      These are weighted higher because they can exfiltrate data even inside SELECT.

    Penalty: SELECT-level risk signals (only applied to SELECT/WITH)
      SELECT *  wildcard                →  +5
      No LIMIT / FETCH clause           →  +5
      UNION / INTERSECT / EXCEPT        → +10
      Subquery depth  (nested SELECTs)  →  +5 per level, max +15
      Cross-join or implicit comma-join → +10

    Final score is clamped to [0, 100].
    """
    clean = _strip_sql(sql)
    if not clean:
        return 50

    first_word = clean.split()[0].upper()
    if first_word not in ('SELECT', 'WITH'):
        score = 70
        kw_matches = _DANGEROUS.findall(clean)
        score += min(50, 25 * len(kw_matches))
        func_matches = _DANGEROUS_FUNCS.findall(clean)
        score += min(80, 40 * len(func_matches))
        return min(100, score)

    # ── SELECT / WITH baseline ────────────────────────────────────────────────
    score = 0

    kw_matches = _DANGEROUS.findall(clean)
    score += min(50, 25 * len(kw_matches))

    func_matches = _DANGEROUS_FUNCS.findall(clean)
    score += min(80, 40 * len(func_matches))

    # SELECT * wildcard
    if re.search(r'SELECT\s+\*', clean, re.IGNORECASE):
        score += 5

    # No LIMIT / FETCH NEXT — unbounded result set
    if not re.search(r'\b(LIMIT|FETCH\s+(?:NEXT|FIRST))\b', clean, re.IGNORECASE):
        score += 5

    # Set operations that can hide injected rows
    if re.search(r'\b(UNION|INTERSECT|EXCEPT)\b', clean, re.IGNORECASE):
        score += 10

    # Subquery depth: count nested SELECT occurrences beyond the first
    nested = len(re.findall(r'\bSELECT\b', clean, re.IGNORECASE)) - 1
    score += min(15, 5 * max(0, nested))

    # Cross-join or implicit comma join: FROM a, b
    if re.search(r'\bCROSS\s+JOIN\b', clean, re.IGNORECASE) or re.search(r'FROM\s+\w[\w.]*\s*,', clean, re.IGNORECASE):
        score += 10

    return min(100, score)


# ── AST-based checks (sqlglot) ──────────────────────────────────────────────
#
# Function names considered dangerous when they appear as an actual function
# *call* in the parsed tree. This mirrors _DANGEROUS_FUNCS but only the true
# function names (not clause keywords like MySQL's INTO OUTFILE, which never
# parses as a Func call and is still caught by the regex fallback).
_AST_DANGEROUS_FUNCS = {
    "pg_read_file", "pg_read_binary_file", "pg_ls_dir", "pg_stat_file",
    "pg_ls_logdir", "pg_ls_waldir", "pg_ls_archive_statusdir",
    "pg_ls_tmpdir", "pg_ls_logicalmapdir", "pg_ls_logicalsnapdir",
    "pg_reload_conf", "pg_rotate_logfile", "pg_terminate_backend",
    "pg_cancel_backend", "pg_start_backup", "pg_stop_backup",
    "pg_sleep", "pg_sleep_for", "pg_sleep_until",
    "lo_import", "lo_export", "lo_creat", "lo_create", "lo_unlink",
    "dblink", "dblink_exec", "dblink_connect", "dblink_open",
    "query_to_xml", "query_to_xmlschema", "cursor_to_xml",
    "pg_copy_to", "pg_copy_from",
    "load_file",
    "utl_file", "utl_http", "utl_smtp", "utl_tcp",
    "xp_cmdshell", "xp_regread", "sp_execute",
    "http_get", "http_post", "http_put", "http_delete",
    "aws_commons", "aws_s3",
    "external_query",
}


@functools.lru_cache(maxsize=256)
def _parse_statements(sql: str, dialect: str | None):
    """Parse `sql` into sqlglot statements.

    Returns None if sqlglot can't confidently parse it — either it raises, or
    it degrades to an opaque `Command` node for syntax it doesn't recognize.
    Both cases mean "the AST layer can't judge this"; callers must fall back
    to the regex checks rather than treating an unparsed query as safe.

    Cached: `is_select_only`, `risk_score`, and `violation_reason` are all
    called with the same (sql, dialect) pair for a single query, so this
    avoids re-parsing the same SQL up to three times per request. Callers
    only read the returned tree (`find`/`find_all`/attribute access) and
    never mutate it, so sharing the cached instance across calls is safe.
    """
    try:
        stmts = sqlglot.parse(sql, read=dialect)
    except Exception:
        return None
    if not stmts or any(s is None or isinstance(s, exp.Command) for s in stmts):
        return None
    return stmts


def _ast_violation(stmts: list) -> str | None:
    """Return a human-readable violation reason, or None if the parsed
    statement(s) are a safe, single, read-only query."""
    if len(stmts) != 1:
        return "Multiple SQL statements are not permitted"

    root = stmts[0]
    if not isinstance(root, exp.Query):
        return f"Query is a '{type(root).__name__.upper()}' statement — only SELECT statements are permitted"

    # A top-level SELECT/WITH can still smuggle a data-modifying statement via
    # a writable CTE, e.g. `WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x`.
    # Reject any mutating/DDL node anywhere in the tree, not just at the root.
    mutation = root.find(exp.Insert, exp.Update, exp.Delete, exp.Merge,
                          exp.Drop, exp.Create, exp.Alter, exp.TruncateTable, exp.Grant)
    if mutation is not None:
        return f"Query contains a nested '{type(mutation).__name__.upper()}' statement — only SELECT statements are permitted"

    for fn in root.find_all(exp.Func):
        name = (fn.name or "").lower()
        if name in _AST_DANGEROUS_FUNCS:
            return f"Query contains forbidden function '{name}'"

    return None


def _ast_risk_score(root: exp.Query) -> int:
    """Score a validated (safe-shaped) Query node using structural signals."""
    score = 0

    func_names = [(fn.name or "").lower() for fn in root.find_all(exp.Func)]
    dangerous_hits = sum(1 for n in func_names if n in _AST_DANGEROUS_FUNCS)
    score += min(80, 40 * dangerous_hits)

    selects = list(root.find_all(exp.Select))

    # SELECT * / t.* wildcard, at any level
    has_star = any(
        isinstance(e, exp.Star) or (isinstance(e, exp.Column) and isinstance(e.this, exp.Star))
        for s in selects for e in s.expressions
    )
    if has_star:
        score += 5

    # No LIMIT on the final result set — unbounded rows returned to the caller
    if not root.args.get("limit"):
        score += 5

    # Set operations that can hide injected rows
    if isinstance(root, exp.SetOperation):
        score += 10

    # Subquery depth: nested SELECTs beyond the outermost one
    nested = len(selects) - 1
    score += min(15, 5 * max(0, nested))

    # Cross-join or implicit comma-join (no ON/USING condition)
    if any(j.kind == "CROSS" or (not j.args.get("on") and not j.args.get("using"))
           for j in root.find_all(exp.Join)):
        score += 10

    return min(100, score)


def is_select_only(sql: str, dialect: str | None = None) -> bool:
    """Return True only for a single, read-only SELECT / WITH…SELECT query.

    Tries the AST-based check first (see module docstring); falls back to
    the regex-based check if sqlglot can't parse `sql`.
    """
    stmts = _parse_statements(sql, dialect)
    if stmts is None:
        return _regex_is_select_only(sql)
    return _ast_violation(stmts) is None


def violation_reason(sql: str, dialect: str | None = None) -> str:
    """Human-readable reason a query was rejected."""
    stmts = _parse_statements(sql, dialect)
    if stmts is None:
        return _regex_violation_reason(sql)
    return _ast_violation(stmts) or "Query is not a read-only SELECT statement"


def catalog_violation(sql: str, dialect: str | None, allowed_catalog: str | None) -> str | None:
    """
    Trino only: reject any table reference that explicitly qualifies a
    *different* catalog than the one this session/token is scoped to.

    A session's db_config carries exactly one catalog (chosen at login) —
    there's no legitimate reason for its generated SQL to reference another
    one. Without this, an MCP client can smuggle a foreign-catalog table
    into the `table_schema` argument it hands the LLM and get a query
    against it, even though the token was only ever issued for one catalog
    (Trino's own authorization, not SQLatte, ends up being the only real
    boundary). Cross-catalog *search* is what discovery tokens are for
    (see DatabaseProvider.discover_tables) — this function is about
    ask_database, a different, narrower door.

    Unqualified table refs (`table`, `schema.table`) are always fine — they
    resolve to the connection's own default catalog. Returns None if
    `allowed_catalog` is falsy (deployment has no catalog restriction
    configured, so there's nothing to lock to) or `dialect` isn't Trino.
    """
    if dialect != "trino" or not allowed_catalog:
        return None

    stmts = _parse_statements(sql, dialect)
    if stmts is None or len(stmts) != 1:
        return None  # same "can't judge it" stance as is_select_only's AST path

    for table in stmts[0].find_all(exp.Table):
        cat = table.catalog
        if cat and cat.lower() != allowed_catalog.lower():
            return (
                f"Query references catalog '{cat}', but this session is scoped to "
                f"'{allowed_catalog}' — cross-catalog queries aren't permitted here."
            )
    return None


def risk_score(sql: str, dialect: str | None = None) -> int:
    """Return an integer risk score 0–100 (lower is safer).

    Uses AST-derived structural signals when sqlglot can parse the query as a
    single Query statement; otherwise falls back to the regex-based scoring
    (see `_regex_risk_score` for the full scoring breakdown).
    """
    stmts = _parse_statements(sql, dialect)
    if stmts is None or len(stmts) != 1 or not isinstance(stmts[0], exp.Query):
        return _regex_risk_score(sql)
    return _ast_risk_score(stmts[0])
