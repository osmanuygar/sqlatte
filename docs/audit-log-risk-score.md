# Audit Log Risk Score

**Source:** `src/core/sql_validator.py` → `risk_score(sql: str) -> int`  
**Range:** 0–100 (0 = safe, 100 = maximum risk)  
**Stored in:** `audit_logs.risk_score`

---

## Key Point: Score Never Blocks

Risk score is **observability data only**. Blocking is handled exclusively by `is_select_only()`, which runs before the database is ever touched. The risk score is always computed and logged regardless of whether the query was allowed or rejected.

| Function | Purpose |
|----------|---------|
| `is_select_only(sql)` | Hard enforcement gate — rejects non-SELECT queries |
| `risk_score(sql)` | Audit signal — logged for monitoring and analytics |

---

## What Gets Blocked

`is_select_only()` rejects any query that:
- Does not start with `SELECT` or `WITH`
- Contains write keywords: `INSERT`, `UPDATE`, `DELETE`, `DROP`, `TRUNCATE`, `ALTER`, `CREATE`, `GRANT`, `REVOKE`, `EXEC`, `CALL`, `MERGE`, `LOAD`, `COPY`, …
- Contains dangerous functions: `pg_read_file`, `dblink`, `xp_cmdshell`, `lo_export`, `pg_sleep`, `http_get`, `EXTERNAL_QUERY`, …

String literals and comments are stripped before all checks to prevent obfuscation bypasses.

This applies to **all entry points** — main widget (`app.py:390`) and MCP/auth widget (`auth_plugin.py:1044`). The `bypass_intent` flag used by MCP only skips intent classification, not SQL validation.

---

## How the Score Is Computed

The score is **additive** and capped at 100.

### Non-SELECT queries (already blocked)

| Condition | Score |
|-----------|-------|
| Empty / unparseable | 50 |
| Starts with a write keyword | 70 + penalties below |

### Dangerous keyword penalty (+25 each, max +50)

Applied when `_DANGEROUS` keywords are found after stripping literals/comments.

### Dangerous function penalty (+40 each, max +80)

Applied when `_DANGEROUS_FUNCS` matches are found. Weighted higher than keywords because these can exfiltrate data even inside a `SELECT` statement.

### SELECT-level signals (only for SELECT / WITH)

| Signal | +Points | Why it matters |
|--------|---------|----------------|
| `SELECT *` wildcard | +5 | Over-exposes columns |
| No `LIMIT` / `FETCH NEXT` | +5 | Unbounded result set |
| `UNION` / `INTERSECT` / `EXCEPT` | +10 | Can smuggle injected rows |
| Nested `SELECT` depth | +5 per level, max +15 | Complex subquery chains |
| `CROSS JOIN` or implicit comma join | +10 | Cartesian product risk |

> For queries that pass `is_select_only()`, only SELECT-level signals apply — keyword and function penalties are irrelevant because those queries are already blocked. The maximum achievable score for a valid SELECT is **45**.

---

## Score Reference

| SQL | Score |
|-----|-------|
| `SELECT id FROM users LIMIT 10` | **0** |
| `SELECT * FROM users LIMIT 10` | **5** |
| `SELECT * FROM users` | **10** |
| `SELECT * FROM a, b` | **20** |
| `WITH cte AS (SELECT …) SELECT * FROM (SELECT … FROM cte) s` | **20** |
| `SELECT pg_read_file('/etc/passwd')` *(blocked)* | **45** |
| `SELECT dblink(…), pg_sleep(5)` *(blocked)* | **85** |
| `DROP TABLE users` *(blocked)* | **95** |
| `INSERT INTO t SELECT pg_read_file(…)` *(blocked)* | **100** |

---

## Interpretation Guide

| Range | Meaning |
|-------|---------|
| 0–9 | Clean SELECT |
| 10–24 | Minor data exposure signals (wildcard, no limit) |
| 25–44 | Multiple exposure signals (set ops, deep subqueries, cross joins) |
| 45–79 | Dangerous function detected — already blocked |
| 80–100 | Multiple dangerous factors — already blocked |
