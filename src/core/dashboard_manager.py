# src/core/dashboard_manager.py
"""
SQLatte Dashboard Manager
Generates auto-dashboards from favorite queries with charts, insights and tables.
Supports both PostgreSQL (analytics enabled) and in-memory (fallback) modes.
"""

import uuid
import json
import math
from datetime import datetime, date, time
from decimal import Decimal
from typing import List, Dict, Optional, Any, Tuple
import logging

logger = logging.getLogger(__name__)


# ============================================
# ROBUST JSON SERIALIZER
# ============================================

class SQLatteJSONEncoder(json.JSONEncoder):
    """
    Extended JSON encoder that handles all Python types returned by DB providers:
    - date, datetime, time  → ISO string
    - Decimal               → float
    - bytes                 → hex string
    - UUID                  → str
    - NaN / Inf             → None  (not valid JSON)
    - Any other unknown     → str(val)
    """
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, date):
            return obj.isoformat()
        if isinstance(obj, time):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            f = float(obj)
            return None if (math.isnan(f) or math.isinf(f)) else f
        if isinstance(obj, bytes):
            return obj.hex()
        try:
            # uuid.UUID and similar
            return str(obj)
        except Exception:
            return super().default(obj)


def _safe_json_dumps(obj: Any) -> str:
    """json.dumps with SQLatteJSONEncoder + NaN/Inf cleanup"""
    return json.dumps(obj, cls=SQLatteJSONEncoder)


def _sanitize_value(val: Any) -> Any:
    """
    Recursively convert a single value to JSON-safe Python primitive.
    Used before storing data in charts / metric summaries.
    """
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, datetime):
        return val.isoformat()
    if isinstance(val, date):
        return val.isoformat()
    if isinstance(val, time):
        return val.isoformat()
    if isinstance(val, Decimal):
        f = float(val)
        return None if (math.isnan(f) or math.isinf(f)) else f
    if isinstance(val, float):
        return None if (math.isnan(val) or math.isinf(val)) else val
    if isinstance(val, (int,)):
        return val
    if isinstance(val, bytes):
        return val.hex()
    if isinstance(val, (list, tuple)):
        return [_sanitize_value(v) for v in val]
    if isinstance(val, dict):
        return {k: _sanitize_value(v) for k, v in val.items()}
    # Fallback: try numeric, else string
    try:
        return str(val)
    except Exception:
        return None


def sanitize_row(row: Any, columns: List[str] = None) -> list:
    """Convert a DB row (list, tuple, or dict) to a JSON-safe list"""
    if isinstance(row, dict):
        return [_sanitize_value(row.get(c)) for c in (columns or row.keys())]
    return [_sanitize_value(v) for v in row]


def sanitize_data(columns: List[str], data: List[Any]) -> List[list]:
    """Sanitize entire result set to JSON-safe nested list"""
    return [sanitize_row(row, columns) for row in data]


# ============================================
# COLUMN TYPE ANALYZER
# ============================================

def analyze_columns(columns: List[str], data: List[List[Any]]) -> Dict:
    """
    Analyze query result columns to detect metrics and dimensions.

    Returns:
        {
          "metrics": ["revenue", "order_count"],      # numeric cols
          "dimensions": ["city", "product_name"],     # string/date cols
          "date_cols": ["created_at", "dt"],          # date-like cols
          "metric_summaries": {"revenue": {"sum": x, "avg": y, "max": z, "min": w}}
        }
    """
    if not columns or not data:
        return {"metrics": [], "dimensions": [], "date_cols": [], "metric_summaries": {}}

    metrics = []
    dimensions = []
    date_cols = []
    metric_summaries = {}

    # Sample up to 20 rows for type detection
    sample = data[:20]

    for i, col in enumerate(columns):
        col_lower = col.lower()
        values = [row[i] if isinstance(row, (list, tuple)) else row.get(col) for row in sample]
        non_null = [v for v in values if v is not None and v != ""]

        if not non_null:
            dimensions.append(col)
            continue

        # Detect date columns by name pattern
        is_date_name = any(kw in col_lower for kw in ["date", "time", "dt", "day", "month", "year", "created", "updated"])

        # Try to cast as float
        numeric_vals = []
        for v in non_null:
            try:
                numeric_vals.append(float(v))
            except (TypeError, ValueError):
                pass

        numeric_ratio = len(numeric_vals) / len(non_null) if non_null else 0

        if numeric_ratio >= 0.8 and not is_date_name:
            # Treat as metric
            metrics.append(col)
            if numeric_vals:
                metric_summaries[col] = {
                    "sum": round(sum(numeric_vals), 2),
                    "avg": round(sum(numeric_vals) / len(numeric_vals), 2),
                    "max": round(max(numeric_vals), 2),
                    "min": round(min(numeric_vals), 2),
                    "count": len(numeric_vals)
                }
        else:
            if is_date_name:
                date_cols.append(col)
                dimensions.append(col)
            else:
                dimensions.append(col)

    return {
        "metrics": metrics,
        "dimensions": dimensions,
        "date_cols": date_cols,
        "metric_summaries": metric_summaries
    }


def _looks_like_date(val: str) -> bool:
    """Quick check: does this string look like a real date (not 'Monday', 'Q1', etc.)"""
    import re as _re
    v = str(val).strip()
    return bool(
        _re.fullmatch(r'\d{4}', v) or                          # 2024
        _re.fullmatch(r'\d{4}-\d{2}', v) or                   # 2024-01
        _re.fullmatch(r'\d{8}', v) or                           # 20240101
        _re.search(r'\d{4}[-/]\d{2}[-/]\d{2}', v) or        # 2024-01-15
        _re.search(r'\d{2}[-/]\d{2}[-/]\d{4}', v)            # 15/01/2024
    )


def _parse_date_key(val):
    """
    Parse a date string into a comparable sort key.
    Handles: ISO dates, YYYYMMDD, YYYY-MM, YYYY, datetime strings.
    Falls back to raw string (works correctly for ISO-formatted strings).
    """
    import re as _re
    from datetime import datetime as _dt
    v = str(val).strip()

    # YYYYMMDD  e.g. "20240115"
    if _re.fullmatch(r'\d{8}', v):
        return v  # lexicographic = chronological for this format

    # YYYY-MM  e.g. "2024-01"
    if _re.fullmatch(r'\d{4}-\d{2}', v):
        return v

    # YYYY  e.g. "2024"
    if _re.fullmatch(r'\d{4}', v):
        return v

    formats = [
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%d-%m-%Y",
        "%Y/%m/%d",
    ]
    for fmt in formats:
        try:
            return _dt.strptime(v, fmt)
        except ValueError:
            pass
    return v  # fallback: raw string sort


def generate_chart_configs(
    columns: List[str],
    data: List[List[Any]],
    analysis: Dict,
    max_charts: int = 20
) -> List[Dict]:
    """
    Auto-generate Chart.js configs from query results.

    Rules:
    - date_col × each metric  → line chart (chronologically sorted)
    - string dim × each metric → bar chart (sorted by value desc, top 25)
    - All combinations are generated, capped at max_charts=20
    """
    if not columns or not data or not (analysis.get("metrics") or []):
        return []

    charts = []
    metrics = analysis.get("metrics", [])
    date_cols = analysis.get("date_cols", [])
    dimensions = [d for d in analysis.get("dimensions", []) if d not in date_cols]

    COLORS = [
        "rgba(212, 165, 116, 0.85)",
        "rgba(74, 222, 128, 0.75)",
        "rgba(96, 165, 250, 0.75)",
        "rgba(248, 113, 113, 0.75)",
        "rgba(167, 139, 250, 0.75)",
        "rgba(251, 191, 36, 0.75)",
        "rgba(166, 124, 82, 0.85)",
        "rgba(45, 212, 191, 0.75)",
        "rgba(236, 72, 153, 0.75)",
        "rgba(107, 68, 35, 0.85)",
    ]
    BORDER = [c.replace("0.85", "1").replace("0.75", "1") for c in COLORS]

    def _cidx(name):
        try:
            return columns.index(name)
        except ValueError:
            return None

    def _agg(dim_col, metric_col):
        di, mi = _cidx(dim_col), _cidx(metric_col)
        if di is None or mi is None:
            return {}
        acc: Dict[str, float] = {}
        for row in data:
            rd = row if isinstance(row, (list, tuple)) else [row.get(c) for c in columns]
            dv = str(rd[di]) if rd[di] is not None else "NULL"
            try:
                mv = float(rd[mi]) if rd[mi] is not None else 0.0
            except (TypeError, ValueError):
                mv = 0.0
            acc[dv] = acc.get(dv, 0.0) + mv
        return acc

    def extract_bar(dim_col, metric_col, top_n=25):
        """
        Preserve original query row order.
        Aggregates duplicate dim values (sum) but keeps first-seen insertion order.
        Only falls back to value-desc sort when there are more rows than top_n
        (i.e. truncation is needed — then show the most significant ones).
        """
        di, mi = _cidx(dim_col), _cidx(metric_col)
        if di is None or mi is None:
            return [], []

        # Use an ordered dict to preserve first-seen row order
        seen_order = []
        agg: Dict[str, float] = {}
        for row in data:
            rd = row if isinstance(row, (list, tuple)) else [row.get(c) for c in columns]
            dv = str(rd[di]) if rd[di] is not None else "NULL"
            try:
                mv = float(rd[mi]) if rd[mi] is not None else 0.0
            except (TypeError, ValueError):
                mv = 0.0
            if dv not in agg:
                seen_order.append(dv)
            agg[dv] = agg.get(dv, 0.0) + mv

        if len(seen_order) <= top_n:
            # All rows fit → keep original order
            items = [(k, agg[k]) for k in seen_order]
        else:
            # Too many rows → show top-N by value (truncation case only)
            items = sorted(agg.items(), key=lambda x: x[1], reverse=True)[:top_n]

        return [i[0] for i in items], [round(i[1], 2) for i in items]

    def extract_timeseries(date_col, metric_col):
        """
        For date columns: sort chronologically.
        If values can't be parsed as real dates (e.g. 'Monday', 'Q1'),
        fall back to original query row order instead of alphabetical.
        """
        di, mi = _cidx(date_col), _cidx(metric_col)
        if di is None or mi is None:
            return [], []

        # Collect in original row order first
        seen_order = []
        agg: Dict[str, float] = {}
        for row in data:
            rd = row if isinstance(row, (list, tuple)) else [row.get(c) for c in columns]
            dv = str(rd[di]) if rd[di] is not None else "NULL"
            try:
                mv = float(rd[mi]) if rd[mi] is not None else 0.0
            except (TypeError, ValueError):
                mv = 0.0
            if dv not in agg:
                seen_order.append(dv)
            agg[dv] = agg.get(dv, 0.0) + mv

        # Try chronological sort — only apply if ALL values parse successfully
        parsed = []
        all_parsed = True
        for k in seen_order:
            pk = _parse_date_key(k)
            # _parse_date_key returns a datetime if parsed, else the raw string
            # If it returned the raw string unchanged → not a real date
            if pk == k and not _looks_like_date(k):
                all_parsed = False
                break
            parsed.append((k, pk, agg[k]))

        if all_parsed and parsed:
            try:
                parsed.sort(key=lambda x: x[1])
                items = [(x[0], x[2]) for x in parsed]
            except TypeError:
                items = [(k, agg[k]) for k in seen_order]
        else:
            # Not real dates → preserve original query order
            items = [(k, agg[k]) for k in seen_order]

        return [i[0] for i in items], [round(i[1], 2) for i in items]

    ci = 0  # color rotation index

    # ── 1. Line charts: every date_col × every metric ──
    for date_col in date_cols:
        for metric in metrics:
            if len(charts) >= max_charts:
                break
            labels, values = extract_timeseries(date_col, metric)
            if not labels:
                continue
            charts.append({
                "type": "line",
                "title": f"{metric} over {date_col}",
                "x_col": date_col,
                "y_col": metric,
                "chart_config": {
                    "type": "line",
                    "data": {
                        "labels": labels,
                        "datasets": [{
                            "label": metric,
                            "data": values,
                            "borderColor": BORDER[ci % len(BORDER)],
                            "backgroundColor": COLORS[ci % len(COLORS)],
                            "fill": True,
                            "tension": 0.4,
                            "pointRadius": 4,
                            "pointHoverRadius": 7,
                        }]
                    },
                    "options": _chart_options(f"{metric} / {date_col}", x_type="time_category")
                }
            })
            ci += 1

    # ── 2. Bar charts: every string dim × every metric ──
    for dim in dimensions:
        for metric in metrics:
            if len(charts) >= max_charts:
                break
            labels, values = extract_bar(dim, metric)
            if not labels:
                continue
            charts.append({
                "type": "bar",
                "title": f"{metric} by {dim}",
                "x_col": dim,
                "y_col": metric,
                "chart_config": {
                    "type": "bar",
                    "data": {
                        "labels": labels,
                        "datasets": [{
                            "label": metric,
                            "data": values,
                            "backgroundColor": COLORS[ci % len(COLORS)],
                            "borderColor": BORDER[ci % len(BORDER)],
                            "borderWidth": 1,
                            "borderRadius": 6,
                        }]
                    },
                    "options": _chart_options(f"{metric} by {dim}")
                }
            })
            ci += 1

    # ── 3. Fallback: no dims/dates → metric comparison charts ──
    # Handles pure-aggregate results like:
    #   SELECT SUM(revenue), COUNT(*), AVG(margin) FROM orders WHERE dt=...
    if not charts and metrics:
        summaries = analysis.get("metric_summaries", {})

        if len(data) == 1:
            # Single row aggregate: all metrics as one grouped bar
            labels = [m.replace("_", " ").title() for m in metrics]
            values = []
            for m in metrics:
                mi = _cidx(m)
                val = data[0][mi] if mi is not None and data[0][mi] is not None else 0
                try:
                    values.append(round(float(val), 2))
                except (TypeError, ValueError):
                    values.append(0)

            if any(v != 0 for v in values):
                charts.append({
                    "type": "bar",
                    "title": "Metrics Overview",
                    "x_col": "metric",
                    "y_col": "value",
                    "chart_config": {
                        "type": "bar",
                        "data": {
                            "labels": labels,
                            "datasets": [{
                                "label": "Value",
                                "data": values,
                                "backgroundColor": COLORS[:len(labels)],
                                "borderColor": BORDER[:len(labels)],
                                "borderWidth": 1,
                                "borderRadius": 6,
                            }]
                        },
                        "options": _chart_options("Metrics Overview")
                    }
                })

        elif len(data) > 1:
            # Multiple rows, no dim/date: use row index as x-axis, one chart per metric
            row_labels = [str(i + 1) for i in range(len(data))]

            for metric in metrics:
                if len(charts) >= max_charts:
                    break
                mi = _cidx(metric)
                if mi is None:
                    continue
                values = []
                for row in data:
                    rd = row if isinstance(row, (list, tuple)) else [row.get(c) for c in columns]
                    try:
                        values.append(round(float(rd[mi]), 2) if rd[mi] is not None else 0)
                    except (TypeError, ValueError):
                        values.append(0)

                if not any(v != 0 for v in values):
                    continue

                charts.append({
                    "type": "bar",
                    "title": metric.replace("_", " ").title(),
                    "x_col": "row",
                    "y_col": metric,
                    "chart_config": {
                        "type": "bar",
                        "data": {
                            "labels": row_labels,
                            "datasets": [{
                                "label": metric,
                                "data": values,
                                "backgroundColor": COLORS[ci % len(COLORS)],
                                "borderColor": BORDER[ci % len(BORDER)],
                                "borderWidth": 1,
                                "borderRadius": 6,
                            }]
                        },
                        "options": _chart_options(metric.replace("_", " ").title())
                    }
                })
                ci += 1

            # SUM comparison chart when multiple metrics, multiple rows
            if summaries and len(summaries) >= 2 and len(charts) < max_charts:
                sum_labels = [m.replace("_", " ").title() for m in summaries]
                sum_values = [round(v["sum"], 2) for v in summaries.values()]
                if any(v != 0 for v in sum_values):
                    charts.append({
                        "type": "bar",
                        "title": "Total Comparison (SUM)",
                        "x_col": "metric",
                        "y_col": "sum",
                        "chart_config": {
                            "type": "bar",
                            "data": {
                                "labels": sum_labels,
                                "datasets": [{
                                    "label": "Total",
                                    "data": sum_values,
                                    "backgroundColor": COLORS[:len(sum_labels)],
                                    "borderColor": BORDER[:len(sum_labels)],
                                    "borderWidth": 1,
                                    "borderRadius": 6,
                                }]
                            },
                            "options": _chart_options("Total Comparison (SUM)")
                        }
                    })

    return charts


def _chart_options(title: str, x_type: str = "category") -> Dict:
    """Shared Chart.js options - SQLatte dark theme"""
    return {
        "responsive": True,
        "maintainAspectRatio": False,
        "plugins": {
            "legend": {
                "position": "bottom",
                "labels": {"color": "#e0e0e0", "font": {"size": 12}}
            },
            "title": {
                "display": True,
                "text": title,
                "color": "#D4A574",
                "font": {"size": 14, "weight": "bold"}
            }
        },
        "scales": {
            "x": {
                "ticks": {"color": "#888", "maxRotation": 45},
                "grid": {"color": "#2a2a2a"}
            },
            "y": {
                "ticks": {"color": "#888"},
                "grid": {"color": "#2a2a2a"}
            }
        }
    }


def generate_metric_cards(analysis: Dict) -> List[Dict]:
    """Generate summary metric cards from column analysis"""
    cards = []
    for col, stats in analysis["metric_summaries"].items():
        cards.append({
            "column": col,
            "label": col.replace("_", " ").title(),
            "sum": stats["sum"],
            "avg": stats["avg"],
            "max": stats["max"],
            "min": stats["min"],
            "count": stats["count"]
        })
    return cards


# ============================================
# DASHBOARD MANAGER
# ============================================

class DashboardManager:
    """
    Manages dashboard CRUD operations.
    Uses PostgreSQL when analytics is enabled, fallback to in-memory.
    """

    def __init__(self, analytics_db=None):
        """
        Args:
            analytics_db: AnalyticsDB instance (PostgreSQL). None = in-memory mode.
        """
        self.db = analytics_db
        self._memory_store: Dict[str, Dict] = {}  # fallback

        if self.db is not None:
            self._init_tables()
            logger.info("✅ Dashboard Manager initialized (PostgreSQL)")
        else:
            logger.info("✅ Dashboard Manager initialized (in-memory)")

    def _init_tables(self):
        """Create dashboard tables in PostgreSQL"""
        try:
            with self.db.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS dashboards (
                            id TEXT PRIMARY KEY,
                            query_id TEXT NOT NULL,
                            title TEXT NOT NULL,
                            description TEXT,
                            question TEXT,
                            sql TEXT,
                            column_analysis JSONB DEFAULT '{}',
                            chart_configs JSONB DEFAULT '[]',
                            metric_cards JSONB DEFAULT '[]',
                            cached_columns JSONB DEFAULT '[]',
                            cached_data JSONB DEFAULT '[]',
                            cached_insights JSONB DEFAULT '[]',
                            row_count INTEGER DEFAULT 0,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );

                        CREATE INDEX IF NOT EXISTS idx_dashboards_query_id
                            ON dashboards(query_id);
                        CREATE INDEX IF NOT EXISTS idx_dashboards_created_at
                            ON dashboards(created_at DESC);
                    """)
            logger.info("✅ Dashboard tables created/verified")
        except Exception as e:
            logger.error(f"❌ Failed to create dashboard tables: {e}")
            raise

    # ----------------------------------------
    # CREATE
    # ----------------------------------------

    def create_dashboard(
        self,
        query_id: str,
        title: str,
        question: str,
        sql: str,
        columns: List[str],
        data: List[List[Any]],
        insights: List[Dict],
        description: str = ""
    ) -> Dict:
        """
        Create a new dashboard from query results.
        Analyzes columns → generates charts + metric cards.
        """
        dashboard_id = str(uuid.uuid4())
        now = datetime.now()

        # ── Sanitize ALL data FIRST (date, Decimal, bytes → JSON-safe) ──
        data = sanitize_data(columns, data)

        # Analyze columns
        analysis = analyze_columns(columns, data)

        # Generate chart configs
        charts = generate_chart_configs(columns, data, analysis)

        # Generate metric cards
        metric_cards = generate_metric_cards(analysis)

        # Cap cached data at 500 rows to avoid huge JSONB blobs
        cached_data = data[:500]

        dashboard = {
            "id": dashboard_id,
            "query_id": query_id,
            "title": title,
            "description": description,
            "question": question,
            "sql": sql,
            "column_analysis": analysis,
            "chart_configs": charts,
            "metric_cards": metric_cards,
            "cached_columns": columns,
            "cached_data": cached_data,
            "cached_insights": insights,
            "row_count": len(data),
            "created_at": now.isoformat(),
            "updated_at": now.isoformat()
        }

        if self.db is not None:
            self._pg_insert(dashboard)
        else:
            self._memory_store[dashboard_id] = dashboard

        logger.info(
            f"✅ Dashboard created: '{title}' | "
            f"{len(charts)} charts | {len(metric_cards)} metrics | {len(data)} rows"
        )
        return dashboard

    def _pg_insert(self, d: Dict):
        with self.db.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO dashboards (
                        id, query_id, title, description, question, sql,
                        column_analysis, chart_configs, metric_cards,
                        cached_columns, cached_data, cached_insights,
                        row_count, created_at, updated_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (
                    d["id"], d["query_id"], d["title"], d["description"],
                    d["question"], d["sql"],
                    _safe_json_dumps(d["column_analysis"]),
                    _safe_json_dumps(d["chart_configs"]),
                    _safe_json_dumps(d["metric_cards"]),
                    _safe_json_dumps(d["cached_columns"]),
                    _safe_json_dumps(d["cached_data"]),
                    _safe_json_dumps(d["cached_insights"]),
                    d["row_count"],
                    d["created_at"], d["updated_at"]
                ))

    # ----------------------------------------
    # READ
    # ----------------------------------------

    def get_all_dashboards(self) -> List[Dict]:
        """List all dashboards (summary, no cached data)"""
        if self.db is not None:
            try:
                with self.db.get_connection() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute("""
                            SELECT id, query_id, title, description, question,
                                   row_count, created_at, updated_at,
                                   jsonb_array_length(chart_configs) as chart_count,
                                   jsonb_array_length(metric_cards) as metric_count,
                                   jsonb_array_length(cached_insights) as insight_count
                            FROM dashboards
                            ORDER BY created_at DESC
                        """)
                        rows = cursor.fetchall()
                        return [self._row_to_summary(row) for row in rows]
            except Exception as e:
                logger.error(f"❌ get_all_dashboards error: {e}")
                return []
        else:
            return [
                {
                    "id": d["id"],
                    "query_id": d["query_id"],
                    "title": d["title"],
                    "description": d["description"],
                    "question": d["question"],
                    "row_count": d["row_count"],
                    "chart_count": len(d["chart_configs"]),
                    "metric_count": len(d["metric_cards"]),
                    "insight_count": len(d["cached_insights"]),
                    "created_at": d["created_at"],
                    "updated_at": d["updated_at"]
                }
                for d in sorted(
                    self._memory_store.values(),
                    key=lambda x: x["created_at"],
                    reverse=True
                )
            ]

    def _row_to_summary(self, row) -> Dict:
        """Convert DB row to summary dict"""
        return {
            "id": row["id"],
            "query_id": row["query_id"],
            "title": row["title"],
            "description": row["description"] or "",
            "question": row["question"] or "",
            "row_count": row["row_count"] or 0,
            "chart_count": row["chart_count"] or 0,
            "metric_count": row["metric_count"] or 0,
            "insight_count": row["insight_count"] or 0,
            "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else row["created_at"],
            "updated_at": row["updated_at"].isoformat() if hasattr(row["updated_at"], "isoformat") else row["updated_at"],
        }

    def get_dashboard(self, dashboard_id: str) -> Optional[Dict]:
        """Get full dashboard with cached data and charts"""
        if self.db is not None:
            try:
                with self.db.get_connection() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute(
                            "SELECT * FROM dashboards WHERE id = %s",
                            (dashboard_id,)
                        )
                        row = cursor.fetchone()
                        if not row:
                            return None
                        return self._row_to_full(row)
            except Exception as e:
                logger.error(f"❌ get_dashboard error: {e}")
                return None
        else:
            return self._memory_store.get(dashboard_id)

    def _row_to_full(self, row) -> Dict:
        """Convert DB row to full dashboard dict"""
        def parse_json(val):
            if val is None:
                return []
            if isinstance(val, (dict, list)):
                return val
            try:
                return json.loads(val)
            except Exception:
                return []

        return {
            "id": row["id"],
            "query_id": row["query_id"],
            "title": row["title"],
            "description": row["description"] or "",
            "question": row["question"] or "",
            "sql": row["sql"] or "",
            "column_analysis": parse_json(row["column_analysis"]),
            "chart_configs": parse_json(row["chart_configs"]),
            "metric_cards": parse_json(row["metric_cards"]),
            "cached_columns": parse_json(row["cached_columns"]),
            "cached_data": parse_json(row["cached_data"]),
            "cached_insights": parse_json(row["cached_insights"]),
            "row_count": row["row_count"] or 0,
            "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else row["created_at"],
            "updated_at": row["updated_at"].isoformat() if hasattr(row["updated_at"], "isoformat") else row["updated_at"],
        }

    # ----------------------------------------
    # UPDATE (Refresh)
    # ----------------------------------------

    def refresh_dashboard(
        self,
        dashboard_id: str,
        columns: List[str],
        data: List[List[Any]],
        insights: List[Dict]
    ) -> Optional[Dict]:
        """
        Refresh dashboard with new query results.
        Re-generates charts/metrics from fresh data.
        """
        existing = self.get_dashboard(dashboard_id)
        if not existing:
            return None

        now = datetime.now()

        # ── Sanitize fresh data FIRST ──
        data = sanitize_data(columns, data)

        analysis = analyze_columns(columns, data)
        charts = generate_chart_configs(columns, data, analysis)
        metric_cards = generate_metric_cards(analysis)
        cached_data = data[:500]

        updates = {
            "column_analysis": analysis,
            "chart_configs": charts,
            "metric_cards": metric_cards,
            "cached_columns": columns,
            "cached_data": cached_data,
            "cached_insights": insights,
            "row_count": len(data),
            "updated_at": now.isoformat()
        }

        if self.db is not None:
            try:
                with self.db.get_connection() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute("""
                            UPDATE dashboards SET
                                column_analysis = %s,
                                chart_configs = %s,
                                metric_cards = %s,
                                cached_columns = %s,
                                cached_data = %s,
                                cached_insights = %s,
                                row_count = %s,
                                updated_at = %s
                            WHERE id = %s
                        """, (
                            _safe_json_dumps(analysis),
                            _safe_json_dumps(charts),
                            _safe_json_dumps(metric_cards),
                            _safe_json_dumps(columns),
                            _safe_json_dumps(cached_data),
                            _safe_json_dumps(insights),
                            len(data),
                            now,
                            dashboard_id
                        ))
            except Exception as e:
                logger.error(f"❌ refresh_dashboard error: {e}")
                return None
        else:
            self._memory_store[dashboard_id].update(updates)

        return self.get_dashboard(dashboard_id)

    # ----------------------------------------
    # DELETE
    # ----------------------------------------

    def delete_dashboard(self, dashboard_id: str) -> bool:
        """Delete a dashboard by ID"""
        if self.db is not None:
            try:
                with self.db.get_connection() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute(
                            "DELETE FROM dashboards WHERE id = %s",
                            (dashboard_id,)
                        )
                        deleted = cursor.rowcount > 0
                        if deleted:
                            logger.info(f"🗑️ Dashboard deleted: {dashboard_id}")
                        return deleted
            except Exception as e:
                logger.error(f"❌ delete_dashboard error: {e}")
                return False
        else:
            if dashboard_id in self._memory_store:
                del self._memory_store[dashboard_id]
                return True
            return False

    def get_stats(self) -> Dict:
        """Return basic dashboard stats"""
        all_d = self.get_all_dashboards()
        return {
            "total_dashboards": len(all_d),
            "storage": "postgresql" if self.db else "in-memory"
        }


# ============================================
# SINGLETON
# ============================================

# Initialized later in app.py startup with analytics_db
dashboard_manager: Optional[DashboardManager] = None


def initialize_dashboard_manager(analytics_db=None) -> DashboardManager:
    global dashboard_manager
    dashboard_manager = DashboardManager(analytics_db)
    return dashboard_manager


def get_dashboard_manager() -> Optional[DashboardManager]:
    return dashboard_manager