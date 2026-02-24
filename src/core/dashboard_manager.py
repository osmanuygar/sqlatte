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


def generate_chart_configs(
    columns: List[str],
    data: List[List[Any]],
    analysis: Dict,
    max_charts: int = 6
) -> List[Dict]:
    """
    Auto-generate Chart.js config objects from query results.

    Strategy:
      - For each dimension x metric combination → bar chart
      - If date col exists → line chart for time series
      - Max categories per chart: 20 (top by metric value)
    """
    charts = []
    metrics = analysis["metrics"]
    dimensions = [d for d in analysis["dimensions"] if d not in analysis["date_cols"]]
    date_cols = analysis["date_cols"]

    COLORS = [
        "rgba(212, 165, 116, 0.85)",   # SQLatte primary
        "rgba(166, 124, 82, 0.85)",
        "rgba(107, 68, 35, 0.85)",
        "rgba(74, 222, 128, 0.75)",
        "rgba(96, 165, 250, 0.75)",
        "rgba(248, 113, 113, 0.75)",
        "rgba(167, 139, 250, 0.75)",
        "rgba(251, 191, 36, 0.75)",
    ]
    BORDER_COLORS = [c.replace("0.85", "1").replace("0.75", "1") for c in COLORS]

    def extract_chart_data(dim_col: str, metric_col: str, top_n: int = 20) -> Tuple[List, List]:
        """Extract labels/values for a dim x metric pair, sorted by metric desc"""
        dim_idx = columns.index(dim_col) if dim_col in columns else None
        met_idx = columns.index(metric_col) if metric_col in columns else None

        if dim_idx is None or met_idx is None:
            return [], []

        agg = {}
        for row in data:
            row_data = row if isinstance(row, (list, tuple)) else [row.get(c) for c in columns]
            dim_val = str(row_data[dim_idx]) if row_data[dim_idx] is not None else "NULL"
            try:
                met_val = float(row_data[met_idx]) if row_data[met_idx] is not None else 0
            except (TypeError, ValueError):
                met_val = 0
            agg[dim_val] = agg.get(dim_val, 0) + met_val

        # Sort by value desc, take top_n
        sorted_items = sorted(agg.items(), key=lambda x: x[1], reverse=True)[:top_n]
        labels = [item[0] for item in sorted_items]
        values = [round(item[1], 2) for item in sorted_items]
        return labels, values

    def extract_time_series(date_col: str, metric_col: str) -> Tuple[List, List]:
        """Extract time-series data sorted by date"""
        date_idx = columns.index(date_col) if date_col in columns else None
        met_idx = columns.index(metric_col) if metric_col in columns else None

        if date_idx is None or met_idx is None:
            return [], []

        agg = {}
        for row in data:
            row_data = row if isinstance(row, (list, tuple)) else [row.get(c) for c in columns]
            date_val = str(row_data[date_idx]) if row_data[date_idx] is not None else "NULL"
            try:
                met_val = float(row_data[met_idx]) if row_data[met_idx] is not None else 0
            except (TypeError, ValueError):
                met_val = 0
            agg[date_val] = agg.get(date_val, 0) + met_val

        sorted_items = sorted(agg.items(), key=lambda x: x[0])
        return [i[0] for i in sorted_items], [round(i[1], 2) for i in sorted_items]

    color_idx = 0

    # 1. Time series charts (date dim × metric)
    for date_col in date_cols[:1]:  # max 1 date col
        for metric in metrics[:2]:  # max 2 metrics per date
            if len(charts) >= max_charts:
                break
            labels, values = extract_time_series(date_col, metric)
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
                            "borderColor": BORDER_COLORS[color_idx % len(BORDER_COLORS)],
                            "backgroundColor": COLORS[color_idx % len(COLORS)],
                            "fill": True,
                            "tension": 0.4
                        }]
                    },
                    "options": _chart_options(f"{metric} / {date_col}", x_type="time_category")
                }
            })
            color_idx += 1

    # 2. Bar charts (string dim × metric)
    for dim in dimensions[:3]:  # max 3 dimensions
        for metric in metrics[:2]:  # max 2 metrics per dim
            if len(charts) >= max_charts:
                break
            labels, values = extract_chart_data(dim, metric)
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
                            "backgroundColor": COLORS[color_idx % len(COLORS)],
                            "borderColor": BORDER_COLORS[color_idx % len(BORDER_COLORS)],
                            "borderWidth": 1,
                            "borderRadius": 6
                        }]
                    },
                    "options": _chart_options(f"{metric} by {dim}")
                }
            })
            color_idx += 1

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