"""
Lightweight alerting for security-sensitive AI/MCP-generated queries.

Two independent triggers, either one fires the alert:
  - risk_score (from sql_validator.risk_score) crosses a configured threshold
  - the query text references a column matching an enabled MCP masking
    field_pattern (best-effort word-token scan, not a full SQL parse —
    mcp_sse.py already does the precise sqlglot-based resolution for
    masking itself; this is just a cheap signal for "should someone look")

Disabled by default (config: mcp.security_alerts.enabled). Every failure
path is swallowed and logged — alerting must never break query execution.
"""
import fnmatch
import html
import logging
import re

logger = logging.getLogger(__name__)

_STRING_OR_COMMENT = re.compile(r"'[^']*'|\"[^\"]*\"|--[^\n]*|/\*.*?\*/", re.DOTALL)
_WORD = re.compile(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b')


def _touched_sensitive_fields(sql: str, mask_rules: list) -> list:
    clean = _STRING_OR_COMMENT.sub(' ', sql)
    tokens = {t.lower() for t in _WORD.findall(clean)}
    hits = []
    for rule in mask_rules:
        pattern = rule["field_pattern"]
        if any(fnmatch.fnmatch(tok, pattern) for tok in tokens):
            hits.append(pattern)
    return hits


def check_and_alert(
    *,
    sql: str,
    risk_score: int,
    username: str,
    session_id: str,
    catalog: str = None,
    widget_type: str = "mcp",
) -> None:
    """Fire a security alert if this AI-generated query looks sensitive.

    Best-effort only: any error here is logged and swallowed so alerting
    can never break the query path it observes.
    """
    try:
        from src.core.config_manager_enhanced import config_manager
        cfg = config_manager.get_config().get("mcp", {}).get("security_alerts", {})
        if not cfg.get("enabled", False):
            return
        if widget_type not in cfg.get("apply_to", ["mcp"]):
            return

        threshold = int(cfg.get("risk_threshold", 70))

        from src.core.config_db import get_config_db
        mask_rules = [r for r in get_config_db().list_mask_rules() if r["enabled"]]
        sensitive_hits = _touched_sensitive_fields(sql, mask_rules)

        if risk_score < threshold and not sensitive_hits:
            return

        reasons = []
        if risk_score >= threshold:
            reasons.append(f"risk_score={risk_score} (threshold {threshold})")
        if sensitive_hits:
            reasons.append(f"sensitive fields matched: {', '.join(sensitive_hits)}")

        logger.warning(
            "SECURITY ALERT: user=%s widget=%s catalog=%s session=%s... %s | SQL: %s",
            username, widget_type, catalog, session_id[:8], " | ".join(reasons), sql[:500],
        )

        recipients = cfg.get("notify_emails", [])
        if recipients:
            _send_alert_email(recipients, username, widget_type, catalog, reasons, sql)
    except Exception as e:
        logger.error(f"security_alerts.check_and_alert failed (non-fatal): {e}")


def _send_alert_email(recipients, username, widget_type, catalog, reasons, sql):
    try:
        from src.api.app import email_service
        if not email_service or not email_service.enabled:
            return

        subject = f"⚠️ SQLatte security alert — {username} ({widget_type})"
        body = (
            f"<p><b>User:</b> {html.escape(str(username))}<br>"
            f"<b>Widget:</b> {html.escape(str(widget_type))}<br>"
            f"<b>Catalog:</b> {html.escape(str(catalog))}<br>"
            f"<b>Reasons:</b> {html.escape('; '.join(reasons))}</p>"
            f"<pre>{html.escape(sql[:1000])}</pre>"
        )

        import asyncio
        asyncio.run(email_service.send_email(recipients, subject, body, html=True))
    except Exception as e:
        logger.error(f"security_alerts email send failed (non-fatal): {e}")
