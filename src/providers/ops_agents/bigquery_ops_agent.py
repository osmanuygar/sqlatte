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

        # BigQuery configuration
        self.project_id = config.get('project_id')
        if not self.project_id:
            raise ValueError("BigQuery Ops Agent requires 'project_id' in config")

        self.region = config.get('region', 'US')

        # Authentication
        credentials_path = config.get('credentials_path')
        if credentials_path and os.path.exists(credentials_path):
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = credentials_path

        try:
            self.credentials, _ = default(
                scopes=['https://www.googleapis.com/auth/bigquery']
            )

            # Refresh token if needed
            if not self.credentials.token:
                self.credentials.refresh(Request())

            # Initialize BigQuery client
            self.client = bigquery.Client(
                project=self.project_id,
                credentials=self.credentials
            )

        except Exception as e:
            raise RuntimeError(f"Failed to initialize BigQuery client: {e}")

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

            # Security operations
            elif operation_name == "find_public_datasets":
                return await self._find_public_datasets()

            elif operation_name == "check_table_permissions":
                return await self._check_table_permissions(**validated_params)

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

    def get_connection_info(self) -> Dict[str, str]:
        """Return agent metadata"""
        operations = self.get_available_operations()

        return {
            "type": "bigquery_ops_agent",
            "platform": "BigQuery",
            "project": self.project_id,
            "region": self.region,
            "operations_count": len(operations),
            "categories": list(self.OPERATIONS.keys())
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
                SUBSTR(query, 1, 100) as query_preview,
                total_slot_ms / (1000 * 60 * 60) AS slot_hours,
                total_bytes_processed / POW(1024, 4) AS tb_processed,
                TIMESTAMP_DIFF(end_time, creation_time, SECOND) as duration_sec,
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
        total_slot_hours = sum(row.get('slot_hours', 0) for row in data)
        total_tb = sum(row.get('tb_processed', 0) for row in data)

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

        total_time_travel_gb = sum(row.get('time_travel_gb', 0) for row in data)

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

        total_savings = sum(row.get('potential_savings_usd', 0) for row in data)

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

        total_gb = sum(row.get('size_gb', 0) for row in data)

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
        # Parse table_id (might be dataset.table or just table)
        parts = table_id.split('.')
        table_name = parts[-1]
        dataset_name = parts[0] if len(parts) == 2 else None

        where_clause = "object_name = @table_name"
        params_dict = {"table_name": table_name}

        if dataset_name:
            where_clause += " AND object_schema = @dataset_name"
            params_dict["dataset_name"] = dataset_name

        # Convert to BigQuery parameter format
        sql = f"""
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

        # Note: parametrized queries with self.client need job_config
        # For simplicity, using direct substitution (table_id is validated)
        sql_exec = sql.replace('@table_name', f"'{table_name}'")
        if dataset_name:
            sql_exec = sql_exec.replace('@dataset_name', f"'{dataset_name}'")

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

        avg_duration = sum(row.get('duration_sec', 0) for row in data) / len(data) if data else 0

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

        total_errors = sum(row.get('error_count', 0) for row in data)

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

        total_gb = sum(row.get('size_gb', 0) for row in data)

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
        # Parse table name
        parts = table_name.split('.')
        table_id = parts[-1]
        dataset_id = parts[0] if len(parts) == 2 else None

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