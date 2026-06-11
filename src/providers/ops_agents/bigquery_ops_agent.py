"""
BigQuery Ops Agent - Operational Automation for BigQuery

Provides cost optimization, security audits, performance diagnostics,
and governance automation for BigQuery environments.

Based on the operational_tools.py from BigQuery Ops project,
adapted for SQLatte architecture.
"""

import os
import asyncio
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from google.cloud import bigquery
from google.auth import default
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from .base_ops_agent import (
    BaseOpsAgent,
    OperationResult,
    OperationCategory
)


class BigQueryOpsAgent(BaseOpsAgent):
    """
    BigQuery Operational Agent

    Provides 20+ operational playbooks for:
      - Cost analysis and forecasting
      - Security audits and IAM recommendations
      - Performance diagnostics and optimization
      - Governance and data quality checks

    Configuration:
        config.yaml:
          ops_agent:
            provider: bigquery_ops
            enabled: true
            config:
              project_id: analytics-prod
              region: US
              credentials_path: /secrets/bigquery-ops.json
              allowed_operations:  # Optional whitelist
                - get_expensive_queries
                - forecast_monthly_costs
    """

    # ─────────────────────────────────────────────────────────────
    # OPERATION REGISTRY
    # ─────────────────────────────────────────────────────────────

    OPERATIONS = {
        "cost": [
            {
                "name": "get_expensive_queries",
                "description": "Top 10 most expensive queries by slot hours",
                "params": [
                    {"name": "days", "type": "int", "default": 30, "required": False}
                ],
                "returns": "table",
                "estimated_duration_sec": 5
            },
            {
                "name": "forecast_monthly_costs",
                "description": "Project monthly costs based on recent usage",
                "params": [
                    {"name": "days", "type": "int", "default": 30, "required": False}
                ],
                "returns": "metrics",
                "estimated_duration_sec": 5
            },
            {
                "name": "get_time_travel_consumers",
                "description": "Tables with heavy time travel storage costs",
                "params": [],
                "returns": "table",
                "estimated_duration_sec": 10
            },
            {
                "name": "analyze_storage_compression",
                "description": "Compare logical vs physical storage savings",
                "params": [],
                "returns": "table",
                "estimated_duration_sec": 15
            },
            {
                "name": "identify_large_unpartitioned_tables",
                "description": "Large tables without partitioning (optimization opportunity)",
                "params": [],
                "returns": "table",
                "estimated_duration_sec": 10
            },
            {
                "name": "get_on_demand_vs_flat_rate_analysis",
                "description": "Compare current on-demand spend vs flat-rate reservation tiers",
                "params": [
                    {"name": "days", "type": "int", "default": 30, "required": False}
                ],
                "returns": "metrics",
                "estimated_duration_sec": 5
            }
        ],
        "security": [
            {
                "name": "find_public_datasets",
                "description": "Identify publicly exposed datasets (CRITICAL)",
                "params": [],
                "returns": "table",
                "estimated_duration_sec": 10
            },
            {
                "name": "check_table_permissions",
                "description": "Analyze access control for specific table",
                "params": [
                    {"name": "table_id", "type": "str", "required": True}
                ],
                "returns": "table",
                "estimated_duration_sec": 5
            },
            {
                "name": "audit_service_account_usage",
                "description": "List service accounts that ran queries and how much data they scanned",
                "params": [
                    {"name": "days", "type": "int", "default": 30, "required": False}
                ],
                "returns": "table",
                "estimated_duration_sec": 5
            }
        ],
        "performance": [
            {
                "name": "get_slow_queries",
                "description": "Queries with high execution time",
                "params": [
                    {"name": "days", "type": "int", "default": 7, "required": False},
                    {"name": "min_duration_sec", "type": "int", "default": 60, "required": False}
                ],
                "returns": "table",
                "estimated_duration_sec": 10
            },
            {
                "name": "analyze_data_skew",
                "description": "Diagnose worker skew and bottlenecks for a job",
                "params": [
                    {"name": "job_id", "type": "str", "required": True}
                ],
                "returns": "analysis",
                "estimated_duration_sec": 5
            },
            {
                "name": "check_slot_saturation",
                "description": "Detect slot capacity saturation issues",
                "params": [],
                "returns": "metrics",
                "estimated_duration_sec": 5
            },
            {
                "name": "get_partition_recommendations",
                "description": "BigQuery's official partitioning recommendations",
                "params": [],
                "returns": "table",
                "estimated_duration_sec": 10
            },
            {
                "name": "get_query_errors",
                "description": "Most common query error patterns",
                "params": [
                    {"name": "days", "type": "int", "default": 7, "required": False}
                ],
                "returns": "table",
                "estimated_duration_sec": 5
            },
            {
                "name": "find_full_table_scans",
                "description": "Queries that scanned >= 90% of a large table (missed partition pruning)",
                "params": [
                    {"name": "days", "type": "int", "default": 7, "required": False},
                    {"name": "min_table_size_gb", "type": "int", "default": 1, "required": False}
                ],
                "returns": "table",
                "estimated_duration_sec": 15
            }
        ],
        "governance": [
            {
                "name": "find_unused_tables",
                "description": "Tables with no queries in N days",
                "params": [
                    {"name": "days_inactive", "type": "int", "default": 90, "required": False}
                ],
                "returns": "table",
                "estimated_duration_sec": 10
            },
            {
                "name": "get_recent_table_users",
                "description": "Who accessed which tables recently",
                "params": [
                    {"name": "table_name", "type": "str", "required": True},
                    {"name": "days", "type": "int", "default": 7, "required": False}
                ],
                "returns": "table",
                "estimated_duration_sec": 5
            }
        ]
    }

    # ─────────────────────────────────────────────────────────────
    # INITIALIZATION
    # ─────────────────────────────────────────────────────────────

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

        # Build projects registry from either 'projects' list or legacy single-project keys
        raw_projects = config.get('projects')
        if raw_projects:
            if not isinstance(raw_projects, list) or len(raw_projects) == 0:
                raise ValueError("ops_agent.config.projects must be a non-empty list")
            self._projects: Dict[str, Dict[str, str]] = {
                p['project_id']: {
                    'region': p.get('region', 'US'),
                    'credentials_path': p.get('credentials_path', '')
                }
                for p in raw_projects
            }
            default_project = config.get('default_project') or raw_projects[0]['project_id']
        else:
            # Legacy single-project config
            project_id = config.get('project_id')
            if not project_id:
                raise ValueError("BigQuery Ops Agent requires 'project_id' or 'projects' in config")
            self._projects = {
                project_id: {
                    'region': config.get('region', 'US'),
                    'credentials_path': config.get('credentials_path', '')
                }
            }
            default_project = project_id

        # Activate default project
        self.project_id: str = ''
        self.region: str = ''
        self.client: Optional[bigquery.Client] = None
        self._init_client(default_project)

    def _init_client(self, project_id: str) -> None:
        """Initialize (or re-initialize) the BigQuery client for the given project."""
        if project_id not in self._projects:
            raise ValueError(
                f"Unknown project '{project_id}'. "
                f"Available: {list(self._projects.keys())}"
            )

        proj = self._projects[project_id]
        credentials_path = proj['credentials_path']

        try:
            if credentials_path and os.path.exists(credentials_path):
                credentials = service_account.Credentials.from_service_account_file(
                    credentials_path,
                    scopes=['https://www.googleapis.com/auth/bigquery']
                )
            else:
                credentials, _ = default(
                    scopes=['https://www.googleapis.com/auth/bigquery']
                )
                if not getattr(credentials, 'token', None):
                    credentials.refresh(Request())

            self.project_id = project_id
            self.region = proj['region']
            self.client = bigquery.Client(
                project=self.project_id,
                credentials=credentials
            )

        except Exception as e:
            raise RuntimeError(
                f"Failed to initialize BigQuery client for project '{project_id}': {e}"
            )

    def switch_project(self, project_id: str) -> None:
        """Switch the active project, region, and credentials at runtime."""
        self._init_client(project_id)

    def list_projects(self) -> List[Dict[str, str]]:
        """Return all configured projects with their metadata."""
        return [
            {
                'project_id': pid,
                'region': meta['region'],
                'active': pid == self.project_id
            }
            for pid, meta in self._projects.items()
        ]

    # ─────────────────────────────────────────────────────────────
    # BASE CLASS IMPLEMENTATIONS
    # ─────────────────────────────────────────────────────────────

    def get_available_operations(self) -> List[Dict[str, Any]]:
        """Flatten operation registry with filtering"""
        operations = []

        for category, ops_list in self.OPERATIONS.items():
            for op in ops_list:
                # Apply whitelist if configured
                if not self.is_operation_allowed(op['name']):
                    continue

                operations.append({
                    "name": op["name"],
                    "description": op["description"],
                    "category": category,
                    "params": op.get("params", []),
                    "returns": op.get("returns", "table"),
                    "estimated_duration_sec": op.get("estimated_duration_sec", 5)
                })

        return operations

    async def execute_operation(
        self,
        operation_name: str,
        params: Optional[Dict[str, Any]] = None
    ) -> OperationResult:
        """
        Execute operational playbook

        Routes to appropriate internal method based on operation name
        """
        params = params or {}

        # Check if operation allowed
        if not self.is_operation_allowed(operation_name):
            return OperationResult(
                success=False,
                operation=operation_name,
                data=[],
                error=f"Operation '{operation_name}' not in allowed_operations whitelist"
            )

        # Find operation schema for param validation
        op_schema = None
        for category_ops in self.OPERATIONS.values():
            for op in category_ops:
                if op['name'] == operation_name:
                    op_schema = op
                    break
            if op_schema:
                break

        if not op_schema:
            return OperationResult(
                success=False,
                operation=operation_name,
                data=[],
                error=f"Unknown operation: {operation_name}",
                metadata={"available_operations": [op['name'] for ops in self.OPERATIONS.values() for op in ops]}
            )

        # Validate parameters
        try:
            validated_params = self.validate_params(
                operation_name,
                params,
                op_schema.get('params', [])
            )
        except ValueError as e:
            return OperationResult(
                success=False,
                operation=operation_name,
                data=[],
                error=str(e)
            )

        # Route to implementation
        try:
            # Cost operations
            if operation_name == "get_expensive_queries":
                return await self._get_expensive_queries(**validated_params)

            elif operation_name == "forecast_monthly_costs":
                return await self._forecast_monthly_costs(**validated_params)

            elif operation_name == "get_time_travel_consumers":
                return await self._get_time_travel_consumers()

            elif operation_name == "analyze_storage_compression":
                return await self._analyze_storage_compression()

            elif operation_name == "identify_large_unpartitioned_tables":
                return await self._identify_large_unpartitioned_tables()

            elif operation_name == "get_on_demand_vs_flat_rate_analysis":
                return await self._get_on_demand_vs_flat_rate_analysis(**validated_params)

            # Security operations
            elif operation_name == "find_public_datasets":
                return await self._find_public_datasets()

            elif operation_name == "check_table_permissions":
                return await self._check_table_permissions(**validated_params)

            elif operation_name == "audit_service_account_usage":
                return await self._audit_service_account_usage(**validated_params)

            # Performance operations
            elif operation_name == "get_slow_queries":
                return await self._get_slow_queries(**validated_params)

            elif operation_name == "analyze_data_skew":
                return await self._analyze_data_skew(**validated_params)

            elif operation_name == "check_slot_saturation":
                return await self._check_slot_saturation()

            elif operation_name == "get_partition_recommendations":
                return await self._get_partition_recommendations()

            elif operation_name == "get_query_errors":
                return await self._get_query_errors(**validated_params)

            elif operation_name == "find_full_table_scans":
                return await self._find_full_table_scans(**validated_params)

            # Governance operations
            elif operation_name == "find_unused_tables":
                return await self._find_unused_tables(**validated_params)

            elif operation_name == "get_recent_table_users":
                return await self._get_recent_table_users(**validated_params)

            else:
                return OperationResult(
                    success=False,
                    operation=operation_name,
                    data=[],
                    error=f"Operation '{operation_name}' not implemented yet"
                )

        except Exception as e:
            return OperationResult(
                success=False,
                operation=operation_name,
                data=[],
                error=f"Execution error: {str(e)}"
            )

    def get_connection_info(self) -> Dict[str, Any]:
        """Return agent metadata"""
        operations = self.get_available_operations()

        return {
            "type": "bigquery_ops_agent",
            "platform": "BigQuery",
            "project": self.project_id,
            "region": self.region,
            "operations_count": len(operations),
            "categories": list(self.OPERATIONS.keys()),
            "projects": self.list_projects()
        }

    async def health_check(self) -> Dict[str, Any]:
        """Verify credentials and access"""
        try:
            # Test query to INFORMATION_SCHEMA
            sql = f"""
                SELECT COUNT(*) as dataset_count
                FROM `{self.project_id}.region-{self.region}.INFORMATION_SCHEMA.SCHEMATA`
                LIMIT 1
            """

            query_job = self.client.query(sql)
            result = list(query_job.result())[0]

            return {
                "healthy": True,
                "project": self.project_id,
                "region": self.region,
                "datasets_accessible": result['dataset_count'],
                "message": "BigQuery Ops Agent ready",
                "last_check": datetime.utcnow().isoformat() + "Z"
            }

        except Exception as e:
            return {
                "healthy": False,
                "error": str(e),
                "last_check": datetime.utcnow().isoformat() + "Z"
            }

    # ─────────────────────────────────────────────────────────────
    # INTERNAL HELPER
    # ─────────────────────────────────────────────────────────────

    async def _run_query(self, sql: str) -> List[Dict[str, Any]]:
        """
        Execute SQL and return results as list of dicts

        Runs in thread pool to avoid blocking event loop
        """
        loop = asyncio.get_event_loop()

        def _execute():
            try:
                query_job = self.client.query(sql)
                results = query_job.result()
                return [dict(row) for row in results]
            except Exception as e:
                raise RuntimeError(f"Query execution failed: {e}")

        return await loop.run_in_executor(None, _execute)

    # ─────────────────────────────────────────────────────────────
    # COST OPERATIONS
    # ─────────────────────────────────────────────────────────────

    async def _get_expensive_queries(self, days: int = 30) -> OperationResult:
        """
        Top 10 most expensive queries by slot hours

        Ported from operational_tools.py → get_expensive_queries_by_slot_hours()
        """
        sql = f"""
            SELECT
                job_id,
                user_email,
                query AS query_text,
                SUBSTR(query, 1, 100) AS query_preview,
                total_slot_ms / (1000 * 60 * 60) AS slot_hours,
                total_bytes_processed / POW(1024, 4) AS tb_processed,
                TIMESTAMP_DIFF(end_time, creation_time, SECOND) AS duration_sec,
                creation_time
            FROM `{self.project_id}.region-{self.region}.INFORMATION_SCHEMA.JOBS_BY_PROJECT`
            WHERE creation_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
                AND job_type = 'QUERY'
                AND state = 'DONE'
                AND total_slot_ms > 0
            ORDER BY total_slot_ms DESC
            LIMIT 10
        """

        data = await self._run_query(sql)

        # Calculate summary stats
        total_slot_hours = sum(row.get('slot_hours') or 0 for row in data)
        total_tb = sum(row.get('tb_processed') or 0 for row in data)

        summary = (
            f"Top 10 queries consumed {total_slot_hours:.2f} slot hours "
            f"and processed {total_tb:.2f} TB in last {days} days"
        )

        recommendations = []
        if total_slot_hours > 1000:
            recommendations.append("Consider enabling query result caching")
            recommendations.append("Review materialized view opportunities")

        # Generate chart
        chart = self._generate_chart_config(
            data=data,
            x_key='job_id',
            y_key='slot_hours',
            chart_type='bar',
            title=f'Top 10 Expensive Queries (Last {days} Days)'
        )

        return OperationResult(
            success=True,
            operation="get_expensive_queries",
            data=data,
            summary=summary,
            recommendations=recommendations,
            visualization=chart,
            metadata={"days_analyzed": days}
        )

    async def _forecast_monthly_costs(self, days: int = 30) -> OperationResult:
        """
        Project monthly costs based on recent usage

        Ported from operational_tools.py → forecast_monthly_costs()
        """
        sql = f"""
            WITH DailyUsage AS (
                SELECT 
                    DATE(creation_time) as usage_date,
                    SUM(total_slot_ms) / (1000*60*60) as daily_slot_hours,
                    SUM(total_bytes_billed) / POW(1024, 4) as daily_tb_billed
                FROM `{self.project_id}.region-{self.region}.INFORMATION_SCHEMA.JOBS_BY_PROJECT`
                WHERE creation_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
                    AND state = 'DONE'
                GROUP BY 1
            )
            SELECT 
                ROUND(AVG(daily_slot_hours), 2) as avg_daily_slot_hours,
                ROUND(AVG(daily_tb_billed), 4) as avg_daily_tb_billed,
                ROUND(AVG(daily_slot_hours) * 30, 2) as forecasted_monthly_slot_hours,
                ROUND(AVG(daily_tb_billed) * 30, 4) as forecasted_monthly_tb_billed,
                COUNT(*) as days_with_activity
            FROM DailyUsage
        """

        data = await self._run_query(sql)

        if not data:
            return OperationResult(
                success=False,
                operation="forecast_monthly_costs",
                data=[],
                summary="Insufficient data for forecast",
                error="No query activity found in the specified period"
            )

        forecast = data[0]
        monthly_slot_hours = forecast.get('forecasted_monthly_slot_hours', 0)
        monthly_tb = forecast.get('forecasted_monthly_tb_billed', 0)

        summary = (
            f"Projected monthly usage: {monthly_slot_hours:.2f} slot hours, "
            f"{monthly_tb:.4f} TB billed (based on last {days} days average)"
        )

        recommendations = [
            f"Projection based on {forecast.get('days_with_activity', 0)} days of activity",
            "Linear projection - actual costs may vary with usage patterns"
        ]

        if monthly_slot_hours > 2000:
            recommendations.append(
                "⚠️ High slot usage detected. Consider slot reservations for cost savings."
            )

        return OperationResult(
            success=True,
            operation="forecast_monthly_costs",
            data=data,
            summary=summary,
            recommendations=recommendations,
            metadata={
                "analysis_period_days": days,
                "projection_method": "linear_average"
            }
        )

    async def _get_time_travel_consumers(self) -> OperationResult:
        """
        Tables with heavy time travel storage costs

        Ported from operational_tools.py → get_top_time_travel_consumers()
        """
        sql = f"""
            SELECT 
                table_schema AS dataset,
                table_name,
                total_physical_bytes / POW(1024, 3) AS total_gb,
                time_travel_physical_bytes / POW(1024, 3) AS time_travel_gb,
                ROUND(SAFE_DIVIDE(time_travel_physical_bytes, total_physical_bytes) * 100, 2) AS time_travel_pct
            FROM `{self.project_id}.region-{self.region}.INFORMATION_SCHEMA.TABLE_STORAGE`
            WHERE time_travel_physical_bytes > 0
            ORDER BY time_travel_physical_bytes DESC
            LIMIT 20
        """

        data = await self._run_query(sql)

        total_time_travel_gb = sum(row.get('time_travel_gb') or 0 for row in data)

        summary = f"Found {len(data)} tables with time travel storage, totaling {total_time_travel_gb:.2f} GB"

        recommendations = []
        if total_time_travel_gb > 100:
            recommendations.append(
                "⚠️ Significant time travel storage detected. "
                "Review retention policies or consider shorter time travel windows."
            )

        chart = self._generate_chart_config(
            data=data[:10],  # Top 10 for chart
            x_key='table_name',
            y_key='time_travel_gb',
            chart_type='bar',
            title='Top 10 Time Travel Storage Consumers'
        )

        return OperationResult(
            success=True,
            operation="get_time_travel_consumers",
            data=data,
            summary=summary,
            recommendations=recommendations,
            visualization=chart
        )

    # ═══════════════════════════════════════════════════
    # COST OPERATIONS (CONTINUED)
    # ═══════════════════════════════════════════════════

    async def _analyze_storage_compression(self) -> OperationResult:
        """
        Compare logical vs physical storage costs
        Estimates potential savings from physical billing model
        """
        LOGICAL_ACTIVE = 0.02
        LOGICAL_LONG_TERM = 0.01
        PHYSICAL_ACTIVE = 0.04
        PHYSICAL_LONG_TERM = 0.02

        sql = f"""
            WITH StorageData AS (
                SELECT 
                    t.table_schema, 
                    t.table_name,
                    t.active_logical_bytes,
                    t.long_term_logical_bytes,
                    t.active_physical_bytes,
                    t.long_term_physical_bytes,
                    t.time_travel_physical_bytes,
                    t.fail_safe_physical_bytes,
                    t.total_logical_bytes,
                    t.total_physical_bytes
                FROM `{self.project_id}.region-{self.region}.INFORMATION_SCHEMA.TABLE_STORAGE` AS t
                WHERE t.total_physical_bytes > 0
            ),
            CostCalculation AS (
                SELECT
                    *,
                    ((active_logical_bytes / POW(1024, 3)) * {LOGICAL_ACTIVE}) + 
                    ((long_term_logical_bytes / POW(1024, 3)) * {LOGICAL_LONG_TERM}) AS monthly_logical_cost,
                    
                    ((active_physical_bytes / POW(1024, 3)) * {PHYSICAL_ACTIVE}) + 
                    ((long_term_physical_bytes / POW(1024, 3)) * {PHYSICAL_LONG_TERM}) +
                    (((time_travel_physical_bytes + fail_safe_physical_bytes) / POW(1024, 3)) * {PHYSICAL_ACTIVE}) AS monthly_physical_cost
                FROM StorageData
            )
            SELECT 
                table_schema, 
                table_name,
                ROUND(SAFE_DIVIDE(total_logical_bytes, total_physical_bytes), 2) AS compression_ratio,
                ROUND(monthly_logical_cost, 2) AS current_monthly_cost_usd,
                ROUND(monthly_physical_cost, 2) AS physical_model_cost_usd,
                ROUND(monthly_logical_cost - monthly_physical_cost, 2) AS potential_savings_usd,
                total_logical_bytes / POW(1024, 3) AS total_gb
            FROM CostCalculation
            ORDER BY potential_savings_usd DESC 
            LIMIT 20
        """

        data = await self._run_query(sql)

        total_savings = sum(row.get('potential_savings_usd') or 0 for row in data)

        summary = f"Analyzed {len(data)} tables. Potential savings: ${total_savings:.2f}/month with physical billing"

        recommendations = [
            "Savings are indicative (US Multi-region list prices)",
            "Physical billing model charges for actual storage used",
            "Contact Google Cloud Sales to enable physical billing"
        ]

        chart = self._generate_chart_config(
            data=data[:10],
            x_key='table_name',
            y_key='potential_savings_usd',
            chart_type='bar',
            title='Top 10 Savings Opportunities'
        )

        return OperationResult(
            success=True,
            operation="analyze_storage_compression",
            data=data,
            summary=summary,
            recommendations=recommendations,
            visualization=chart
        )

    async def _identify_large_unpartitioned_tables(self) -> OperationResult:
        """
        Find large tables without partitioning (optimization opportunity)
        """
        sql = f"""
            SELECT 
                t.table_schema, 
                t.table_name, 
                t.total_logical_bytes / POW(1024, 3) AS size_gb
            FROM `{self.project_id}.region-{self.region}.INFORMATION_SCHEMA.TABLE_STORAGE` AS t
            JOIN `{self.project_id}.region-{self.region}.INFORMATION_SCHEMA.TABLES` AS tbl
            ON t.table_schema = tbl.table_schema AND t.table_name = tbl.table_name
            WHERE tbl.ddl NOT LIKE '%PARTITION BY%' 
                AND t.total_logical_bytes > POW(1024, 3)  -- > 1GB
            ORDER BY t.total_logical_bytes DESC 
            LIMIT 20
        """

        data = await self._run_query(sql)

        total_gb = sum(row.get('size_gb') or 0 for row in data)

        summary = f"Found {len(data)} large unpartitioned tables totaling {total_gb:.2f} GB"

        recommendations = []
        if len(data) > 0:
            recommendations.append(
                "⚠️ Consider partitioning these tables by date/timestamp columns"
            )
            recommendations.append(
                "Partitioning reduces scan costs and improves query performance"
            )

        chart = self._generate_chart_config(
            data=data[:10],
            x_key='table_name',
            y_key='size_gb',
            chart_type='bar',
            title='Top 10 Large Unpartitioned Tables'
        )

        return OperationResult(
            success=True,
            operation="identify_large_unpartitioned_tables",
            data=data,
            summary=summary,
            recommendations=recommendations,
            visualization=chart
        )

    # ═══════════════════════════════════════════════════
    # SECURITY OPERATIONS
    # ═══════════════════════════════════════════════════

    async def _find_public_datasets(self) -> OperationResult:
        """
        CRITICAL: Find datasets exposed to allUsers/allAuthenticatedUsers
        """
        exposed = []

        try:
            datasets = list(self.client.list_datasets(project=self.project_id))

            for ds_item in datasets:
                try:
                    dataset_ref = self.client.dataset(ds_item.dataset_id, project=self.project_id)
                    dataset = self.client.get_dataset(dataset_ref)

                    for entry in dataset.access_entries:
                        if entry.special_group in ['allUsers', 'allAuthenticatedUsers']:
                            exposed.append({
                                "dataset": dataset.dataset_id,
                                "grantee": entry.special_group,
                                "role": entry.role,
                                "severity": "CRITICAL"
                            })
                except Exception as inner_e:
                    print(f"Warning: Could not check dataset {ds_item.dataset_id}: {inner_e}")
                    continue

        except Exception as e:
            return OperationResult(
                success=False,
                operation="find_public_datasets",
                data=[],
                error=f"Failed to scan datasets: {e}"
            )

        if not exposed:
            return OperationResult(
                success=True,
                operation="find_public_datasets",
                data=[],
                summary="✅ No publicly exposed datasets found",
                recommendations=["Good security posture maintained"]
            )

        summary = f"🚨 CRITICAL: Found {len(exposed)} publicly exposed datasets!"

        recommendations = [
            "🚨 Immediate action required - these datasets are publicly accessible",
            "Review and revoke public access unless explicitly intended",
            "Use specific user/group grants instead of allUsers/allAuthenticatedUsers"
        ]

        return OperationResult(
            success=True,
            operation="find_public_datasets",
            data=exposed,
            summary=summary,
            recommendations=recommendations
        )


    async def _check_table_permissions(self, table_id: str) -> OperationResult:
        """
        Analyze who has access to a specific table
        """
        from src.core.sql_validator import validate_identifier
        # Parse table_id (might be dataset.table or just table)
        parts = table_id.split('.')
        table_name = validate_identifier(parts[-1])
        dataset_name = validate_identifier(parts[0]) if len(parts) == 2 else None

        # Values are identifier-validated; single-quote escaping is safe for BQ string literals
        table_literal = table_name.replace("'", "")
        dataset_literal = dataset_name.replace("'", "") if dataset_name else None

        where_clause = f"object_name = '{table_literal}'"
        if dataset_literal:
            where_clause += f" AND object_schema = '{dataset_literal}'"

        sql_exec = f"""
            SELECT
                grantee,
                privilege_type,
                object_schema AS dataset,
                object_name AS table
            FROM `{self.project_id}.region-{self.region}.INFORMATION_SCHEMA.OBJECT_PRIVILEGES`
            WHERE object_type = 'TABLE'
                AND {where_clause}
                AND privilege_type = 'SELECT'
        """

        data = await self._run_query(sql_exec)

        summary = f"Found {len(data)} users/groups with SELECT access to {table_id}"

        recommendations = []
        if len(data) > 10:
            recommendations.append("⚠️ Large number of grantees - review for least privilege")

        return OperationResult(
            success=True,
            operation="check_table_permissions",
            data=data,
            summary=summary,
            recommendations=recommendations,
            metadata={"table_id": table_id}
        )

    # ═══════════════════════════════════════════════════
    # PERFORMANCE OPERATIONS
    # ═══════════════════════════════════════════════════

    async def _get_slow_queries(self, days: int = 7, min_duration_sec: int = 60) -> OperationResult:
        """
        Find queries with high execution time
        """
        sql = f"""
            SELECT 
                job_id,
                user_email,
                SUBSTR(query, 1, 100) AS query_preview,
                TIMESTAMP_DIFF(end_time, start_time, SECOND) AS duration_sec,
                total_slot_ms / (1000 * 60 * 60) AS slot_hours,
                creation_time
            FROM `{self.project_id}.region-{self.region}.INFORMATION_SCHEMA.JOBS_BY_PROJECT`
            WHERE creation_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
                AND job_type = 'QUERY'
                AND state = 'DONE'
                AND TIMESTAMP_DIFF(end_time, start_time, SECOND) >= {min_duration_sec}
            ORDER BY duration_sec DESC
            LIMIT 20
        """

        data = await self._run_query(sql)

        avg_duration = sum(row.get('duration_sec') or 0 for row in data) / len(data) if data else 0

        summary = f"Found {len(data)} slow queries (>{min_duration_sec}s). Average: {avg_duration:.1f}s"

        recommendations = []
        if len(data) > 0:
            recommendations.append("Analyze execution plans for slow queries")
            recommendations.append("Consider partitioning, clustering, or materialized views")

        chart = self._generate_chart_config(
            data=data[:10],
            x_key='job_id',
            y_key='duration_sec',
            chart_type='bar',
            title='Top 10 Slowest Queries'
        )

        return OperationResult(
            success=True,
            operation="get_slow_queries",
            data=data,
            summary=summary,
            recommendations=recommendations,
            visualization=chart,
            metadata={"days": days, "min_duration_sec": min_duration_sec}
        )

    async def _analyze_data_skew(self, job_id: str) -> OperationResult:
        """
        Diagnose worker skew and bottlenecks for a specific job
        """
        from src.core.sql_validator import validate_job_id
        try:
            job_id = validate_job_id(job_id)
        except ValueError as exc:
            return OperationResult(success=False, operation="analyze_data_skew", data=[], error=str(exc))

        sql = f"""
            SELECT
                stage_id,
                MAX(slot_ms) AS max_slot_ms,
                AVG(slot_ms) AS avg_slot_ms,
                STDDEV(slot_ms) AS stddev_slot_ms
            FROM `{self.project_id}.region-{self.region}.INFORMATION_SCHEMA.JOBS_TIMELINE_BY_PROJECT`
            WHERE job_id = '{job_id}'
            GROUP BY stage_id
            ORDER BY stage_id
        """

        data = await self._run_query(sql)

        if not data:
            return OperationResult(
                success=False,
                operation="analyze_data_skew",
                data=[],
                error=f"No timeline data found for job_id: {job_id}"
            )

        # Analyze skew
        max_stddev = max(row.get('stddev_slot_ms', 0) for row in data)

        diagnosis = "HEALTHY - No significant skew detected"
        if max_stddev > 100000:  # Arbitrary threshold
            diagnosis = "⚠️ CONFIRMED DATA SKEW - Large standard deviation detected"

        summary = f"Job {job_id}: {diagnosis}"

        recommendations = []
        if "SKEW" in diagnosis:
            recommendations.append("Consider using FARM_FINGERPRINT() salt on skewed join keys")
            recommendations.append("Review data distribution in large tables")

        return OperationResult(
            success=True,
            operation="analyze_data_skew",
            data=data,
            summary=summary,
            recommendations=recommendations,
            metadata={"job_id": job_id, "diagnosis": diagnosis}
        )

    async def _check_slot_saturation(self) -> OperationResult:
        """
        Detect slot capacity saturation issues
        """
        sql = f"""
            WITH SlotUsage AS (
                SELECT 
                    DATE(creation_time) AS usage_date,
                    MAX(total_slot_ms) / (1000 * 60) AS peak_slot_minutes
                FROM `{self.project_id}.region-{self.region}.INFORMATION_SCHEMA.JOBS_BY_PROJECT`
                WHERE creation_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
                GROUP BY 1
            )
            SELECT 
                AVG(peak_slot_minutes) AS avg_peak_slots,
                MAX(peak_slot_minutes) AS max_peak_slots
            FROM SlotUsage
        """

        data = await self._run_query(sql)

        if not data:
            return OperationResult(
                success=True,
                operation="check_slot_saturation",
                data=[],
                summary="Insufficient data for slot analysis"
            )

        result = data[0]
        max_slots = result.get('max_peak_slots', 0)

        health_status = "OK"
        if max_slots > 2000:
            health_status = "⚠️ HIGH - Consider slot reservations"

        summary = f"Slot health: {health_status}. Peak usage: {max_slots:.0f} slot-minutes"

        recommendations = []
        if "HIGH" in health_status:
            recommendations.append("High slot usage detected")
            recommendations.append("Consider purchasing slot reservations for cost savings")

        return OperationResult(
            success=True,
            operation="check_slot_saturation",
            data=data,
            summary=summary,
            recommendations=recommendations,
            metadata={"health_status": health_status}
        )

    async def _get_partition_recommendations(self) -> OperationResult:
        """
        Get BigQuery's official partitioning recommendations
        """
        sql = f"""
            SELECT
                last_updated_time,
                description,
                target_resources,
                primary_impact,
                additional_details
            FROM `{self.project_id}.region-{self.region}.INFORMATION_SCHEMA.RECOMMENDATIONS`
            WHERE recommender = 'google.bigquery.table.PartitionClusterRecommender'
                AND state = 'ACTIVE'
            ORDER BY last_updated_time DESC
            LIMIT 20
        """

        data = await self._run_query(sql)

        summary = f"Found {len(data)} partitioning recommendations from BigQuery"

        recommendations = []
        if len(data) > 0:
            recommendations.append("Apply these official BigQuery recommendations")
            recommendations.append("Partitioning can significantly reduce query costs")

        return OperationResult(
            success=True,
            operation="get_partition_recommendations",
            data=data,
            summary=summary,
            recommendations=recommendations
        )

    async def _get_query_errors(self, days: int = 7) -> OperationResult:
        """
        Most common query error patterns
        """
        sql = f"""
            SELECT 
                error_result.reason AS error_reason, 
                COUNT(*) AS error_count,
                ANY_VALUE(error_result.message) AS sample_message
            FROM `{self.project_id}.region-{self.region}.INFORMATION_SCHEMA.JOBS_BY_PROJECT`
            WHERE creation_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
                AND error_result IS NOT NULL
            GROUP BY 1 
            ORDER BY error_count DESC 
            LIMIT 10
        """

        data = await self._run_query(sql)

        total_errors = sum(row.get('error_count') or 0 for row in data)

        summary = f"Found {total_errors} errors across {len(data)} error types in last {days} days"

        recommendations = []
        if len(data) > 0:
            top_error = data[0].get('error_reason', 'unknown')
            recommendations.append(f"Top error: {top_error}")
            recommendations.append("Review error messages for patterns")

        chart = self._generate_chart_config(
            data=data,
            x_key='error_reason',
            y_key='error_count',
            chart_type='bar',
            title='Top Query Errors'
        )

        return OperationResult(
            success=True,
            operation="get_query_errors",
            data=data,
            summary=summary,
            recommendations=recommendations,
            visualization=chart
        )

    # ═══════════════════════════════════════════════════
    # GOVERNANCE OPERATIONS
    # ═══════════════════════════════════════════════════

    async def _find_unused_tables(self, days_inactive: int = 90) -> OperationResult:
        """
        Find tables with no queries in N days
        """
        sql = f"""
            SELECT DISTINCT 
                t.table_schema AS dataset, 
                t.table_name AS table, 
                t.total_logical_bytes / POW(1024, 3) AS size_gb
            FROM `{self.project_id}.region-{self.region}.INFORMATION_SCHEMA.TABLE_STORAGE` AS t
            WHERE NOT EXISTS (
                SELECT 1 
                FROM `{self.project_id}.region-{self.region}.INFORMATION_SCHEMA.JOBS_BY_PROJECT` AS j,
                UNNEST(j.referenced_tables) AS ref
                WHERE j.creation_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days_inactive} DAY)
                    AND ref.table_id = t.table_name 
                    AND ref.dataset_id = t.table_schema
            ) 
            AND t.total_logical_bytes > 0 
            ORDER BY size_gb DESC 
            LIMIT 50
        """

        data = await self._run_query(sql)

        total_gb = sum(row.get('size_gb') or 0 for row in data)

        summary = f"Found {len(data)} unused tables ({days_inactive}+ days inactive) totaling {total_gb:.2f} GB"

        recommendations = []
        if total_gb > 100:
            recommendations.append(f"⚠️ {total_gb:.1f} GB of unused storage detected")
            recommendations.append("Consider archiving or deleting unused tables")

        chart = self._generate_chart_config(
            data=data[:10],
            x_key='table',
            y_key='size_gb',
            chart_type='bar',
            title='Top 10 Unused Tables by Size'
        )

        return OperationResult(
            success=True,
            operation="find_unused_tables",
            data=data,
            summary=summary,
            recommendations=recommendations,
            visualization=chart,
            metadata={"days_inactive": days_inactive}
        )

    async def _get_recent_table_users(self, table_name: str, days: int = 7) -> OperationResult:
        """
        Who accessed which table recently
        """
        from src.core.sql_validator import validate_identifier
        parts = table_name.split('.')
        try:
            table_id = validate_identifier(parts[-1])
            dataset_id = validate_identifier(parts[0]) if len(parts) == 2 else None
        except ValueError as exc:
            return OperationResult(success=False, operation="get_recent_table_users", data=[], error=str(exc))

        days = max(1, min(int(days), 365))

        extra_filter = ""
        if dataset_id:
            extra_filter = f"AND ref.dataset_id = '{dataset_id}'"

        sql = f"""
            SELECT DISTINCT
                user_email,
                creation_time,
                SUBSTR(query, 1, 100) AS query_preview
            FROM `{self.project_id}.region-{self.region}.INFORMATION_SCHEMA.JOBS_BY_PROJECT`,
            UNNEST(referenced_tables) AS ref
            WHERE ref.table_id = '{table_id}'
                {extra_filter}
                AND creation_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
            ORDER BY creation_time DESC
            LIMIT 50
        """

        data = await self._run_query(sql)

        unique_users = len(set(row.get('user_email', '') for row in data))

        summary = f"Found {unique_users} unique users who accessed {table_name} in last {days} days"

        return OperationResult(
            success=True,
            operation="get_recent_table_users",
            data=data,
            summary=summary,
            metadata={"table_name": table_name, "days": days}
        )

    # ═══════════════════════════════════════════════════
    # COST OPERATIONS (CONTINUED)
    # ═══════════════════════════════════════════════════

    async def _get_on_demand_vs_flat_rate_analysis(self, days: int = 30) -> OperationResult:
        """
        Compare current on-demand spend vs flat-rate slot reservation tiers.

        On-demand price: $6.25/TB billed (US multi-region).
        Flat-rate tiers (approximate monthly commitments):
          - 100 slots  → $2,000/month
          - 500 slots  → $10,000/month
          - 2000 slots → $40,000/month
        """
        ON_DEMAND_PRICE_PER_TB = 6.25

        FLAT_RATE_TIERS = [
            {"slots": 100,  "monthly_usd": 2_000},
            {"slots": 500,  "monthly_usd": 10_000},
            {"slots": 2_000, "monthly_usd": 40_000},
        ]

        sql = f"""
            WITH DailyUsage AS (
                SELECT
                    DATE(creation_time) AS usage_date,
                    SUM(total_bytes_billed) / POW(1024, 4)      AS daily_tb_billed,
                    SUM(total_slot_ms) / (1000.0 * 3600)        AS daily_slot_hours,
                    MAX(total_slot_ms / (1000.0 * 60))          AS peak_slot_minutes
                FROM `{self.project_id}.region-{self.region}.INFORMATION_SCHEMA.JOBS_BY_PROJECT`
                WHERE creation_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
                    AND state = 'DONE'
                    AND job_type = 'QUERY'
                GROUP BY 1
            )
            SELECT
                COUNT(*)                                               AS active_days,
                ROUND(SUM(daily_tb_billed), 4)                        AS total_tb_billed,
                ROUND(AVG(daily_tb_billed), 6)                        AS avg_daily_tb,
                ROUND(SUM(daily_tb_billed) * (30.0 / {days}), 4)     AS projected_monthly_tb,
                ROUND(AVG(daily_slot_hours), 2)                       AS avg_daily_slot_hours,
                ROUND(MAX(peak_slot_minutes), 0)                      AS peak_slots_observed
            FROM DailyUsage
        """

        data = await self._run_query(sql)

        if not data or not data[0].get('active_days'):
            return OperationResult(
                success=False,
                operation="get_on_demand_vs_flat_rate_analysis",
                data=[],
                error="No query activity found in the specified period"
            )

        row = data[0]
        monthly_tb = float(row.get('projected_monthly_tb', 0))
        on_demand_monthly_usd = round(monthly_tb * ON_DEMAND_PRICE_PER_TB, 2)
        peak_slots = float(row.get('peak_slots_observed', 0))

        # Build comparison rows
        comparison = []
        recommended_tier = None
        for tier in FLAT_RATE_TIERS:
            savings = round(on_demand_monthly_usd - tier['monthly_usd'], 2)
            comparison.append({
                "tier_slots": tier['slots'],
                "flat_rate_monthly_usd": tier['monthly_usd'],
                "on_demand_monthly_usd": on_demand_monthly_usd,
                "savings_usd": savings,
                "recommendation": "SAVE" if savings > 0 else "OVERPAY"
            })
            if savings > 0 and recommended_tier is None:
                recommended_tier = tier

        summary = (
            f"Projected on-demand spend: ${on_demand_monthly_usd:,.2f}/month "
            f"({monthly_tb:.4f} TB × ${ON_DEMAND_PRICE_PER_TB}/TB). "
            f"Peak slots observed: {peak_slots:.0f}."
        )

        recommendations = []
        if recommended_tier:
            recommendations.append(
                f"Flat-rate at {recommended_tier['slots']} slots "
                f"(${recommended_tier['monthly_usd']:,}/mo) would save "
                f"${on_demand_monthly_usd - recommended_tier['monthly_usd']:,.2f}/month."
            )
            recommendations.append(
                "Flat-rate is cost-effective when usage is consistent — "
                "review day-over-day variance before committing."
            )
        else:
            recommendations.append(
                "On-demand pricing is currently cheaper than all flat-rate tiers."
            )
            recommendations.append(
                "Revisit if monthly spend exceeds $2,000 (100-slot break-even)."
            )

        chart = self._generate_chart_config(
            data=comparison,
            x_key='tier_slots',
            y_key='flat_rate_monthly_usd',
            chart_type='bar',
            title='Flat-Rate Tiers vs On-Demand Cost'
        )

        return OperationResult(
            success=True,
            operation="get_on_demand_vs_flat_rate_analysis",
            data=comparison,
            summary=summary,
            recommendations=recommendations,
            visualization=chart,
            metadata={
                "days_analyzed": days,
                "on_demand_price_per_tb": ON_DEMAND_PRICE_PER_TB,
                "projected_monthly_tb": monthly_tb,
                "projected_monthly_on_demand_usd": on_demand_monthly_usd,
                "peak_slots_observed": peak_slots
            }
        )

    # ═══════════════════════════════════════════════════
    # SECURITY OPERATIONS (CONTINUED)
    # ═══════════════════════════════════════════════════

    async def _audit_service_account_usage(self, days: int = 30) -> OperationResult:
        """
        List service accounts that ran queries, how much data they scanned,
        and how many slot hours they consumed.

        Service accounts are identified by emails containing
        'iam.gserviceaccount.com' or 'developer.gserviceaccount.com'.
        """
        sql = f"""
            SELECT
                user_email                                              AS service_account,
                COUNT(*)                                                AS query_count,
                ROUND(SUM(total_bytes_processed) / POW(1024, 4), 4)   AS total_tb_scanned,
                ROUND(SUM(total_slot_ms) / (1000.0 * 3600), 2)        AS total_slot_hours,
                ROUND(AVG(total_bytes_processed) / POW(1024, 3), 2)   AS avg_gb_per_query,
                MAX(creation_time)                                      AS last_seen
            FROM `{self.project_id}.region-{self.region}.INFORMATION_SCHEMA.JOBS_BY_PROJECT`
            WHERE creation_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
                AND job_type = 'QUERY'
                AND state = 'DONE'
                AND (
                    user_email LIKE '%iam.gserviceaccount.com'
                    OR user_email LIKE '%developer.gserviceaccount.com'
                )
            GROUP BY user_email
            ORDER BY total_tb_scanned DESC
            LIMIT 30
        """

        data = await self._run_query(sql)

        if not data:
            return OperationResult(
                success=True,
                operation="audit_service_account_usage",
                data=[],
                summary=f"No service account query activity found in the last {days} days."
            )

        total_tb = sum(float(row.get('total_tb_scanned', 0)) for row in data)
        total_queries = sum(int(row.get('query_count', 0)) for row in data)

        # Flag high-volume SAs (top 20% of TB scanned)
        threshold_tb = sorted(
            [float(r.get('total_tb_scanned', 0)) for r in data], reverse=True
        )[max(0, len(data) // 5)]

        for row in data:
            row['risk_flag'] = (
                "HIGH" if float(row.get('total_tb_scanned', 0)) >= threshold_tb and len(data) > 1
                else "OK"
            )

        high_risk = [r for r in data if r['risk_flag'] == "HIGH"]

        summary = (
            f"Found {len(data)} service accounts that ran {total_queries:,} queries "
            f"scanning {total_tb:.2f} TB total in last {days} days."
        )

        recommendations = []
        if high_risk:
            recommendations.append(
                f"⚠️ {len(high_risk)} high-volume SA(s) detected — verify they use "
                "column/row-level security and SELECT only what they need."
            )
        recommendations.append(
            "Ensure each SA follows least-privilege: grant access per dataset, not project-wide."
        )
        recommendations.append(
            "Consider Authorized Views for SAs that only need aggregated results."
        )

        chart = self._generate_chart_config(
            data=data[:10],
            x_key='service_account',
            y_key='total_tb_scanned',
            chart_type='bar',
            title='Top 10 Service Accounts by TB Scanned'
        )

        return OperationResult(
            success=True,
            operation="audit_service_account_usage",
            data=data,
            summary=summary,
            recommendations=recommendations,
            visualization=chart,
            metadata={"days_analyzed": days, "sa_count": len(data)}
        )

    # ═══════════════════════════════════════════════════
    # PERFORMANCE OPERATIONS (CONTINUED)
    # ═══════════════════════════════════════════════════

    async def _find_full_table_scans(
        self, days: int = 7, min_table_size_gb: int = 1
    ) -> OperationResult:
        """
        Find queries that scanned >= 90% of a large table's logical bytes —
        a strong indicator of missed partition pruning or absent WHERE clauses.

        Joins JOBS_BY_PROJECT.referenced_tables with TABLE_STORAGE to compare
        bytes processed against actual table size.
        """
        min_bytes = int(min_table_size_gb) * (1024 ** 3)

        sql = f"""
            WITH LargeTables AS (
                SELECT
                    table_schema   AS dataset_id,
                    table_name     AS table_id,
                    total_logical_bytes
                FROM `{self.project_id}.region-{self.region}.INFORMATION_SCHEMA.TABLE_STORAGE`
                WHERE total_logical_bytes >= {min_bytes}
            ),
            JobRefs AS (
                SELECT
                    j.job_id,
                    j.user_email,
                    j.creation_time,
                    SUBSTR(j.query, 1, 120)         AS query_preview,
                    j.total_bytes_processed,
                    ref.dataset_id                  AS ref_dataset,
                    ref.table_id                    AS ref_table
                FROM `{self.project_id}.region-{self.region}.INFORMATION_SCHEMA.JOBS_BY_PROJECT` AS j,
                UNNEST(j.referenced_tables) AS ref
                WHERE j.creation_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
                    AND j.job_type = 'QUERY'
                    AND j.state = 'DONE'
                    AND j.total_bytes_processed > 0
            )
            SELECT
                jr.job_id,
                jr.user_email,
                jr.query_preview,
                jr.ref_dataset                                          AS dataset,
                jr.ref_table                                            AS table_name,
                ROUND(jr.total_bytes_processed / POW(1024, 3), 2)      AS bytes_processed_gb,
                ROUND(lt.total_logical_bytes / POW(1024, 3), 2)        AS table_size_gb,
                ROUND(
                    SAFE_DIVIDE(jr.total_bytes_processed, lt.total_logical_bytes) * 100, 1
                )                                                       AS scan_pct,
                jr.creation_time
            FROM JobRefs AS jr
            JOIN LargeTables AS lt
                ON jr.ref_dataset = lt.dataset_id
               AND jr.ref_table   = lt.table_id
            WHERE SAFE_DIVIDE(jr.total_bytes_processed, lt.total_logical_bytes) >= 0.9
            ORDER BY jr.total_bytes_processed DESC
            LIMIT 25
        """

        data = await self._run_query(sql)

        if not data:
            return OperationResult(
                success=True,
                operation="find_full_table_scans",
                data=[],
                summary=(
                    f"No full table scans detected on tables >= {min_table_size_gb} GB "
                    f"in the last {days} days. Partition pruning appears healthy."
                )
            )

        total_tb_wasted = sum(float(r.get('bytes_processed_gb', 0)) for r in data) / 1024
        unique_tables = len(set(
            f"{r.get('dataset')}.{r.get('table_name')}" for r in data
        ))

        summary = (
            f"Found {len(data)} full-table-scan job(s) across {unique_tables} table(s), "
            f"processing {total_tb_wasted:.2f} TB total in last {days} days."
        )

        recommendations = [
            "Add partition filters (WHERE date_col >= ...) to avoid full scans on partitioned tables.",
            "Consider clustering on frequently filtered columns to reduce bytes read.",
            "Use INFORMATION_SCHEMA.PARTITIONS to confirm partition pruning is active."
        ]

        if total_tb_wasted > 1:
            recommendations.insert(
                0,
                f"⚠️ {total_tb_wasted:.2f} TB scanned unnecessarily — "
                "fixing these queries could significantly reduce on-demand costs."
            )

        chart = self._generate_chart_config(
            data=data[:10],
            x_key='table_name',
            y_key='bytes_processed_gb',
            chart_type='bar',
            title='Top 10 Full Table Scans by GB Processed'
        )

        return OperationResult(
            success=True,
            operation="find_full_table_scans",
            data=data,
            summary=summary,
            recommendations=recommendations,
            visualization=chart,
            metadata={
                "days_analyzed": days,
                "min_table_size_gb": min_table_size_gb,
                "unique_tables_affected": unique_tables
            }
        )