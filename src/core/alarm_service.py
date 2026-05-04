"""
Alarm Service for BigQuery Ops
Evaluates cost thresholds (TB processed) and sends email / creates Jira tickets.
"""

import json
import logging
import urllib.error
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


@dataclass
class AlarmCondition:
    field: str = "total_tb_processed"   # total_tb_processed | max_tb_processed
    operator: str = "gt"                # gt | gte | lt | lte
    threshold: float = 0.5


@dataclass
class AlarmNotifications:
    email: bool = True
    jira: bool = False


@dataclass
class AlarmRule:
    id: str
    name: str
    enabled: bool
    operation: str              # e.g. get_expensive_queries
    params: Dict                # e.g. {"days": 1}
    condition: AlarmCondition
    notifications: AlarmNotifications
    schedule: str               # cron, e.g. "0 8 * * *"
    recipients: List[str]       # email recipients
    created_at: str
    updated_at: str
    project_id: Optional[str] = None   # None = use active project
    last_triggered: Optional[str] = None
    last_status: Optional[str] = None  # triggered | ok | error


@dataclass
class AlarmHistoryEntry:
    id: str
    alarm_id: str
    alarm_name: str
    triggered_at: str
    status: str                 # triggered | ok | error
    value: float
    threshold: float
    message: str
    email_sent: bool = False
    jira_ticket: Optional[str] = None   # Jira issue key e.g. "OPS-123"
    insights: List[Dict] = field(default_factory=list)


class AlarmService:
    def __init__(self, config: Dict, email_service=None, ops_agent=None, jira_config: Optional[Dict] = None):
        self.config = config
        self.email_service = email_service
        self.ops_agent = ops_agent
        self.jira_config = jira_config or {}
        self.alarms: Dict[str, AlarmRule] = {}
        self.history: List[AlarmHistoryEntry] = []

        storage = config.get('storage_path', 'config/alarms.json')
        self.storage_path = Path(storage)
        self._load()
        logger.info(f"✅ Alarm service initialized with {len(self.alarms)} alarm(s)")

    def set_ops_agent(self, ops_agent):
        self.ops_agent = ops_agent

    def set_jira_config(self, jira_config: Dict):
        self.jira_config = jira_config

    # ──────────────────────────────────────────────────
    # PERSISTENCE
    # ──────────────────────────────────────────────────

    def _load(self):
        try:
            if self.storage_path.exists():
                with open(self.storage_path, 'r') as f:
                    data = json.load(f)
                for a in data.get('alarms', []):
                    cond = AlarmCondition(**a.pop('condition'))
                    notif_raw = a.pop('notifications', {})
                    notif = AlarmNotifications(**notif_raw) if notif_raw else AlarmNotifications()
                    self.alarms[a['id']] = AlarmRule(condition=cond, notifications=notif, **a)
                self.history = [AlarmHistoryEntry(**h) for h in data.get('history', [])[-500:]]
        except Exception as e:
            logger.error(f"Failed to load alarms: {e}")

    def _save(self):
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                'alarms': [asdict(a) for a in self.alarms.values()],
                'history': [asdict(h) for h in self.history[-500:]]
            }
            with open(self.storage_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save alarms: {e}")

    # ──────────────────────────────────────────────────
    # CRUD
    # ──────────────────────────────────────────────────

    def create_alarm(self, name: str, operation: str, params: Dict,
                     condition: Dict, notifications: Dict, schedule: str,
                     recipients: List[str], project_id: Optional[str] = None,
                     enabled: bool = True) -> AlarmRule:
        now = datetime.now().isoformat()
        alarm = AlarmRule(
            id=str(uuid.uuid4())[:8],
            name=name,
            enabled=enabled,
            operation=operation,
            params=params,
            condition=AlarmCondition(**condition),
            notifications=AlarmNotifications(**notifications),
            schedule=schedule,
            recipients=recipients,
            project_id=project_id,
            created_at=now,
            updated_at=now,
        )
        self.alarms[alarm.id] = alarm
        self._save()
        return alarm

    def update_alarm(self, alarm_id: str, updates: Dict) -> Optional[AlarmRule]:
        alarm = self.alarms.get(alarm_id)
        if not alarm:
            return None
        if 'condition' in updates:
            alarm.condition = AlarmCondition(**updates.pop('condition'))
        if 'notifications' in updates:
            alarm.notifications = AlarmNotifications(**updates.pop('notifications'))
        for k, v in updates.items():
            if hasattr(alarm, k):
                setattr(alarm, k, v)
        alarm.updated_at = datetime.now().isoformat()
        self._save()
        return alarm

    def delete_alarm(self, alarm_id: str) -> bool:
        if alarm_id not in self.alarms:
            return False
        del self.alarms[alarm_id]
        self._save()
        return True

    def get_alarms(self) -> List[Dict]:
        return [asdict(a) for a in self.alarms.values()]

    def get_alarm_history(self, alarm_id: Optional[str] = None, limit: int = 50) -> List[Dict]:
        hist = self.history if not alarm_id else [h for h in self.history if h.alarm_id == alarm_id]
        return [asdict(h) for h in hist[-limit:]]

    # ──────────────────────────────────────────────────
    # EVALUATION
    # ──────────────────────────────────────────────────

    def _evaluate_condition(self, condition: AlarmCondition, data: List[Dict]) -> tuple[bool, float]:
        if condition.field == "total_tb_processed":
            value = sum(float(row.get('tb_processed', 0) or 0) for row in data)
        elif condition.field == "max_tb_processed":
            value = max((float(row.get('tb_processed', 0) or 0) for row in data), default=0.0)
        else:
            value = sum(float(row.get(condition.field, 0) or 0) for row in data)

        ops = {'gt': value > condition.threshold, 'gte': value >= condition.threshold,
               'lt': value < condition.threshold, 'lte': value <= condition.threshold}
        return ops.get(condition.operator, False), round(value, 6)

    async def evaluate_alarm(self, alarm: AlarmRule) -> Dict:
        if not self.ops_agent:
            return {"status": "error", "message": "Ops agent not available"}

        # Switch to alarm's project if specified, restore afterwards
        previous_project = self.ops_agent.project_id
        switched = False
        if alarm.project_id and alarm.project_id != previous_project:
            try:
                self.ops_agent.switch_project(alarm.project_id)
                switched = True
            except Exception as e:
                return {"status": "error", "message": f"Cannot switch to project '{alarm.project_id}': {e}"}

        try:
            result = await self.ops_agent.execute_operation(
                operation_name=alarm.operation,
                params=alarm.params
            )
            if not result.success:
                return {"status": "error", "message": f"Operation failed: {result.error or result.summary or 'unknown error'}"}

            triggered, value = self._evaluate_condition(alarm.condition, result.data)
            status = "triggered" if triggered else "ok"
            op_sym = ">" if alarm.condition.operator in ("gt", "gte") else "<"
            message = (
                f"{'⚠️ ALERT' if triggered else '✅ OK'}: "
                f"{value:.3f} TB {op_sym} {alarm.condition.threshold} TB threshold"
            )

            # Generate AI insights if enabled
            ai_insights = []
            try:
                from src.core.config_manager_enhanced import config_manager
                current_config = config_manager.get_config()
                ops_cfg = current_config.get("ops_agent", {})
                if ops_cfg.get("ai_insights", False) and result.data:
                    prompt_override = current_config.get("prompts", {}).get("ops_insights_generation")
                    if prompt_override:
                        from src.core.llm_insights_engine import get_insights_engine
                        engine = get_insights_engine()
                        if engine and engine.enabled:
                            rows = result.data
                            columns = list(rows[0].keys()) if rows else []
                            data_matrix = [[row.get(col) for col in columns] for row in rows]
                            max_insights = ops_cfg.get("ai_insights_max")
                            ai_insights = engine.generate_insights(
                                columns=columns,
                                data=data_matrix,
                                user_question=alarm.operation,
                                prompt_override=prompt_override,
                                max_insights=max_insights,
                            )
                            logger.info(f"🧠 Generated {len(ai_insights)} AI insights for alarm '{alarm.name}'")
            except Exception as insight_err:
                logger.warning(f"AI insights failed for alarm '{alarm.name}' (non-fatal): {insight_err}")

            email_sent = False
            jira_ticket = None

            if triggered:
                if alarm.notifications.email and alarm.recipients:
                    await self._send_alarm_email(alarm, value, result.data, ai_insights)
                    email_sent = True

                if alarm.notifications.jira and self.jira_config.get('enabled'):
                    jira_ticket = await self._create_jira_ticket(alarm, value, result.data, ai_insights)

            entry = AlarmHistoryEntry(
                id=str(uuid.uuid4())[:8],
                alarm_id=alarm.id,
                alarm_name=alarm.name,
                triggered_at=datetime.now().isoformat(),
                status=status,
                value=value,
                threshold=alarm.condition.threshold,
                message=message,
                email_sent=email_sent,
                jira_ticket=jira_ticket,
                insights=ai_insights,
            )
            self.history.append(entry)
            if triggered:
                alarm.last_triggered = entry.triggered_at
            alarm.last_status = status
            self._save()

            return {
                "status": status,
                "triggered": triggered,
                "value": value,
                "threshold": alarm.condition.threshold,
                "message": message,
                "email_sent": email_sent,
                "jira_ticket": jira_ticket,
                "project_id": self.ops_agent.project_id,
                "insights": ai_insights,
            }

        except Exception as e:
            logger.error(f"Alarm evaluation error for '{alarm.name}': {e}")
            return {"status": "error", "message": str(e)}
        finally:
            # Always restore original project
            if switched:
                try:
                    self.ops_agent.switch_project(previous_project)
                except Exception as e:
                    logger.error(f"Failed to restore project to '{previous_project}': {e}")

    async def evaluate_all_enabled(self):
        """Called by APScheduler – evaluates every enabled alarm sequentially."""
        for alarm in list(self.alarms.values()):
            if alarm.enabled:
                try:
                    await self.evaluate_alarm(alarm)
                except Exception as e:
                    logger.error(f"Alarm '{alarm.name}' evaluation failed: {e}")

    # ──────────────────────────────────────────────────
    # EMAIL
    # ──────────────────────────────────────────────────

    async def _send_alarm_email(self, alarm: AlarmRule, total_tb: float, data: List[Dict], insights: List[Dict] = None):
        if not self.email_service or not self.email_service.enabled:
            logger.warning("Email service unavailable – skipping alarm notification")
            return
        subject = (
            f"⚠️ BigQuery Cost Alert: {total_tb:.3f} TB processed "
            f"(threshold: {alarm.condition.threshold} TB) – {alarm.name}"
        )
        body = self._build_alarm_email(alarm, total_tb, data, insights or [])
        await self.email_service.send_email(
            recipients=alarm.recipients,
            subject=subject,
            body=body,
            html=True,
        )
        logger.info(f"📧 Alarm email sent for '{alarm.name}' → {alarm.recipients}")

    def _build_alarm_email(self, alarm: AlarmRule, total_tb: float, data: List[Dict], insights: List[Dict] = None) -> str:
        timestamp = datetime.now().strftime('%B %d, %Y at %H:%M UTC')
        project_label = alarm.project_id or "default project"
        threshold = alarm.condition.threshold

        # Only rows whose individual tb_processed exceeds the threshold
        over_rows = [r for r in data if float(r.get('tb_processed', 0) or 0) > threshold]
        if not over_rows:
            over_rows = data[:10]  # fallback: show all if none individually exceed

        rows_html = ""
        for row in over_rows:
            tb       = float(row.get('tb_processed', 0) or 0)
            user     = row.get('user_email', 'unknown')
            duration = row.get('duration_sec', 0)
            job_id   = row.get('job_id', '')
            full_sql = str(row.get('query_text') or row.get('query_preview', '')).strip()
            # escape HTML special chars
            safe_sql = full_sql.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            rows_html += f"""
            <tr>
              <td style="padding:10px;border-bottom:1px solid #f0f0f0;font-size:12px;color:#555;vertical-align:top;white-space:nowrap;">{user}</td>
              <td style="padding:10px;border-bottom:1px solid #f0f0f0;font-size:13px;font-weight:700;color:#e17055;text-align:right;vertical-align:top;white-space:nowrap;">{tb:.4f} TB</td>
              <td style="padding:10px;border-bottom:1px solid #f0f0f0;font-size:12px;color:#888;text-align:right;vertical-align:top;white-space:nowrap;">{duration}s</td>
            </tr>
            <tr>
              <td colspan="3" style="padding:0 10px 12px;border-bottom:1px solid #eee;">
                <details>
                  <summary style="font-size:11px;color:#aaa;cursor:pointer;margin-bottom:4px;">
                    Full SQL — job {job_id}
                  </summary>
                  <pre style="margin:6px 0 0;padding:10px 12px;background:#f8f8f8;border-radius:6px;font-size:11px;color:#333;white-space:pre-wrap;word-break:break-all;max-height:300px;overflow-y:auto;">{safe_sql}</pre>
                </details>
              </td>
            </tr>"""

        return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;margin:0;padding:0;background:#f4f4f4;">
  <div style="max-width:720px;margin:40px auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 4px 16px rgba(0,0,0,.12);">
    <div style="background:linear-gradient(135deg,#e17055 0%,#c0392b 100%);padding:32px;text-align:center;">
      <div style="font-size:52px;line-height:1;margin-bottom:12px;">⚠️</div>
      <h1 style="margin:0;color:#fff;font-size:22px;font-weight:700;">BigQuery Cost Alert</h1>
      <p style="margin:8px 0 0;color:rgba(255,255,255,.85);font-size:14px;">{alarm.name} · {project_label}</p>
    </div>
    <div style="padding:28px 30px;">
      <div style="background:#fff5f5;border:2px solid #fecaca;border-radius:10px;padding:22px;text-align:center;margin-bottom:24px;">
        <div style="font-size:13px;color:#888;margin-bottom:6px;text-transform:uppercase;letter-spacing:.8px;">Total TB Processed · Last {alarm.params.get('days', 1)} Day(s)</div>
        <div style="font-size:52px;font-weight:800;color:#e17055;line-height:1;">{total_tb:.3f}</div>
        <div style="font-size:15px;font-weight:600;color:#e17055;margin-top:2px;">TB</div>
        <div style="font-size:13px;color:#aaa;margin-top:8px;">Threshold: {threshold} TB</div>
      </div>
      <h3 style="color:#222;font-size:15px;font-weight:600;margin:0 0 4px;">
        Queries Exceeding {threshold} TB ({len(over_rows)} found)
      </h3>
      <p style="font-size:12px;color:#aaa;margin:0 0 14px;">Only queries individually above the threshold are shown.</p>
      <div style="overflow-x:auto;border-radius:8px;border:1px solid #eee;">
        <table style="width:100%;border-collapse:collapse;">
          <thead>
            <tr style="background:#f8f8f8;">
              <th style="padding:10px;text-align:left;font-size:11px;color:#aaa;font-weight:700;text-transform:uppercase;letter-spacing:.8px;">User</th>
              <th style="padding:10px;text-align:right;font-size:11px;color:#aaa;font-weight:700;text-transform:uppercase;letter-spacing:.8px;">TB Processed</th>
              <th style="padding:10px;text-align:right;font-size:11px;color:#aaa;font-weight:700;text-transform:uppercase;letter-spacing:.8px;">Duration</th>
            </tr>
          </thead>
          <tbody>{rows_html}</tbody>
        </table>
      </div>
      {self._build_insights_html(insights or [])}
    </div>
    <div style="padding:20px 30px;background:#fafafa;border-top:1px solid #eee;text-align:center;">
      <p style="margin:0;font-size:12px;color:#888;">Generated at {timestamp}</p>
      <p style="margin:6px 0 0;font-size:12px;color:#bbb;">Powered by <strong style="color:#D4A574;">SQLatte</strong> ☕ BigQuery Ops Alarms</p>
    </div>
  </div>
</body>
</html>"""

    def _build_insights_html(self, insights: List[Dict]) -> str:
        if not insights:
            return ""
        severity_colors = {"warning": "#e17055", "success": "#00b894", "info": "#0984e3"}
        rows = ""
        for insight in insights:
            icon = insight.get("icon", "💡")
            msg = insight.get("message", "")
            severity = insight.get("severity", "info")
            color = severity_colors.get(severity, "#555")
            rows += (
                f'<li style="padding:8px 0;border-bottom:1px solid #f0f0f0;font-size:13px;color:{color};">'
                f'{icon}&nbsp; {msg}</li>'
            )
        return f"""
      <div style="margin-top:24px;">
        <h3 style="color:#222;font-size:15px;font-weight:600;margin:0 0 10px;">🧠 AI Insights</h3>
        <ul style="list-style:none;margin:0;padding:0;background:#f9f9f9;border-radius:8px;border:1px solid #eee;padding:12px 16px;">
          {rows}
        </ul>
      </div>"""

    # ──────────────────────────────────────────────────
    # JIRA
    # ──────────────────────────────────────────────────

    async def _create_jira_ticket(self, alarm: AlarmRule, total_tb: float, data: List[Dict], insights: List[Dict] = None) -> Optional[str]:
        """Create a Jira issue via REST API v2 (Server/Data Center, Bearer token)."""
        cfg = self.jira_config
        if not cfg.get('enabled'):
            return None

        url = cfg.get('url', '').rstrip('/')
        email = cfg.get('email', '')
        api_token = cfg.get('api_token', '')
        project_key = cfg.get('project_key', '')
        issue_type = cfg.get('issue_type', 'Bug')
        priority = cfg.get('priority', 'High')

        if not all([url, api_token, project_key]):
            logger.warning("Jira config incomplete – skipping ticket creation")
            return None

        project_label = alarm.project_id or "default"
        threshold = alarm.condition.threshold

        # Only rows individually above threshold
        over_rows = [r for r in data if float(r.get('tb_processed', 0) or 0) > threshold]
        if not over_rows:
            over_rows = data[:10]

        query_sections = []
        for i, row in enumerate(over_rows, 1):
            tb = float(row.get('tb_processed', 0) or 0)
            user = row.get('user_email', 'unknown')
            duration = row.get('duration_sec', 0)
            job_id = row.get('job_id', '')
            full_sql = str(row.get('query_text') or row.get('query_preview', '')).strip()
            query_sections.append(
                f"*Query {i}* — {user} | {tb:.4f} TB | {duration}s | Job: {job_id}\n"
                f"{{code:sql}}\n{full_sql}\n{{code}}"
            )
        queries_str = "\n\n".join(query_sections) if query_sections else "N/A"

        summary = f"[BigQuery Cost Alert] {alarm.name} – {total_tb:.3f} TB processed ({project_label})"

        insights_str = ""
        if insights:
            insight_lines = "\n".join(
                f"* {i.get('icon', '💡')} [{i.get('severity', 'info').upper()}] {i.get('message', '')}"
                for i in insights
            )
            insights_str = f"\n\nh3. 🧠 AI Insights\n\n{insight_lines}\n"

        description = (
            f"Alarm *{alarm.name}* triggered on project *{project_label}*.\n\n"
            f"*Total TB Processed* (last {alarm.params.get('days', 1)} day(s)): *{total_tb:.3f} TB*\n"
            f"*Threshold*: {threshold} TB\n"
            f"*Queries above threshold*: {len(over_rows)}\n\n"
            f"----\n\n"
            f"h3. Queries Exceeding {threshold} TB\n\n"
            f"{queries_str}"
            f"{insights_str}\n"
            f"----\n"
            f"_Triggered at: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}_"
        )

        payload = {
            "fields": {
                "project": {"key": project_key},
                "summary": summary,
                "description": description,
                "issuetype": {"name": issue_type},
                #"customfield_19193": [{"id": "19430"}],
            }
        }

        # Jira Server/Data Center: Bearer token auth
        headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        import asyncio
        import urllib.request

        def _post_jira():
            req = urllib.request.Request(
                f"{url}/rest/api/2/issue",
                data=json.dumps(payload).encode(),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read()
                status = resp.status
            logger.info(f"Jira response status={status} body={raw[:1000]!r}")
            if not raw.strip():
                return {}
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                logger.error(f"Jira returned non-JSON (status={status}): {raw[:500].decode(errors='replace')}")
                return {}

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, _post_jira)
            ticket_key = result.get('key', '')
            logger.info(f"🎫 Jira ticket created: {ticket_key} for alarm '{alarm.name}'")
            return ticket_key
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            logger.error(
                f"Failed to create Jira ticket for '{alarm.name}': {e} | "
                f"status={e.code} url={e.url} response_body={body}"
            )
            return None
        except Exception as e:
            logger.error(f"Failed to create Jira ticket for '{alarm.name}': {e}")
            return None


# ──────────────────────────────────────────────────────────
# MODULE-LEVEL SINGLETON
# ──────────────────────────────────────────────────────────

_alarm_service: Optional[AlarmService] = None


def get_alarm_service() -> Optional[AlarmService]:
    return _alarm_service


def initialize_alarm_service(config: Dict, email_service=None, ops_agent=None,
                              jira_config: Optional[Dict] = None) -> AlarmService:
    global _alarm_service
    _alarm_service = AlarmService(config, email_service, ops_agent, jira_config)
    return _alarm_service
