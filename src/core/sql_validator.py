"""
SQL query validator – enforces SELECT-only access.
Strips string literals and comments before analysis to avoid false positives.
"""
import re

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


def is_select_only(sql: str) -> bool:
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
    m2 = _DANGEROUS_FUNCS.search(clean)
    if m2:
        return f"Query contains forbidden function '{m2.group().rstrip('(').strip()}'"
    return "Query is not a read-only SELECT statement"


def risk_score(sql: str) -> int:
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
