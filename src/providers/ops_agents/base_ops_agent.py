"""
SQLatte Ops Agent System - Base Interface

Ops Agents provide operational automation for database platforms.
Different from database providers:
  - Database Provider: Executes ad-hoc SQL queries (SELECT * FROM users)
  - Ops Agent: Executes predefined operational playbooks (get_expensive_queries, analyze_storage)

Use cases:
  - Cost optimization
  - Security audits
  - Performance diagnostics
  - Governance automation
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
from enum import Enum


class OperationCategory(Enum):
    """Operation categories for organizational purposes"""
    COST = "cost"
    SECURITY = "security"
    PERFORMANCE = "performance"
    GOVERNANCE = "governance"
    DIAGNOSTICS = "diagnostics"


class OperationResult:
    """
    Standardized operation result format

    Ensures consistent output across all ops agents
    """

    def __init__(
            self,
            success: bool,
            operation: str,
            data: List[Dict[str, Any]],
            summary: str = "",
            recommendations: Optional[List[str]] = None,
            visualization: Optional[Dict[str, Any]] = None,
            metadata: Optional[Dict[str, Any]] = None,
            error: Optional[str] = None
    ):
        self.success = success
        self.operation = operation
        self.data = data
        self.summary = summary
        self.recommendations = recommendations or []
        self.visualization = visualization
        self.metadata = metadata or {}
        self.error = error

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            "success": self.success,
            "operation": self.operation,
            "data": self.data,
            "summary": self.summary,
            "recommendations": self.recommendations,
            "visualization": self.visualization,
            "metadata": self.metadata,
            "error": self.error,
            "row_count": len(self.data)
        }


class BaseOpsAgent(ABC):
    """
    Abstract base class for operational agents

    Each ops agent implements platform-specific operational playbooks
    for DBA/DevOps automation.

    Example implementations:
      - BigQueryOpsAgent: Cost analysis, slot optimization, security audits
      - PostgresOpsAgent: Vacuum analysis, index recommendations, replication health
      - TrinoOpsAgent: Cluster health, query optimization, resource monitoring
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize ops agent

        Args:
            config: Agent-specific configuration from config.yaml
                Example:
                {
                    "project_id": "my-project",
                    "region": "US",
                    "credentials_path": "/path/to/creds.json",
                    "allowed_operations": ["get_expensive_queries", "..."]
                }
        """
        self.config = config
        self.name = self.__class__.__name__
        self.enabled = True

        # Optional: Restrict operations
        self.allowed_operations = config.get('allowed_operations', None)

    @abstractmethod
    def get_available_operations(self) -> List[Dict[str, Any]]:
        """
        List all available operational playbooks

        Returns:
            List of operation metadata:
            [
                {
                    "name": "get_expensive_queries",
                    "description": "Find top 10 expensive queries by slot hours",
                    "category": "cost",
                    "params": [
                        {"name": "days", "type": "int", "default": 30, "required": False}
                    ],
                    "returns": "table",  # table | metrics | analysis
                    "estimated_duration_sec": 5
                },
                ...
            ]
        """
        pass

    @abstractmethod
    async def execute_operation(
            self,
            operation_name: str,
            params: Optional[Dict[str, Any]] = None
    ) -> OperationResult:
        """
        Execute an operational playbook

        Args:
            operation_name: Name of the operation (e.g., "get_expensive_queries")
            params: Optional parameters {"days": 30, "min_cost": 100}

        Returns:
            OperationResult with:
              - data: List of result rows
              - summary: Human-readable summary
              - recommendations: Actionable suggestions
              - visualization: Chart.js config (optional)

        Raises:
            ValueError: If operation not found or params invalid
            PermissionError: If operation not in allowed_operations
        """
        pass

    @abstractmethod
    def get_connection_info(self) -> Dict[str, str]:
        """
        Return agent metadata

        Returns:
            {
                "type": "bigquery_ops_agent",
                "platform": "BigQuery",
                "project": "my-project",
                "region": "US",
                "operations_count": 25
            }
        """
        pass

    @abstractmethod
    async def health_check(self) -> Dict[str, Any]:
        """
        Verify agent credentials and platform access

        Returns:
            {
                "healthy": True/False,
                "project": "my-project",
                "accessible_resources": 150,
                "message": "Agent ready",
                "last_check": "2024-01-15T10:30:00Z"
            }
        """
        pass

    def is_operation_allowed(self, operation_name: str) -> bool:
        """
        Check if operation is in whitelist

        Args:
            operation_name: Operation to check

        Returns:
            True if allowed (or no whitelist configured)
        """
        if self.allowed_operations is None:
            return True

        return operation_name in self.allowed_operations

    def validate_params(
            self,
            operation_name: str,
            params: Dict[str, Any],
            schema: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Validate and fill default parameters

        Args:
            operation_name: Operation being executed
            params: User-provided parameters
            schema: Parameter schema from get_available_operations()

        Returns:
            Validated parameters with defaults filled

        Raises:
            ValueError: If required param missing or type mismatch
        """
        validated = {}

        for param_def in schema:
            param_name = param_def['name']
            param_type = param_def.get('type', 'str')
            required = param_def.get('required', False)
            default = param_def.get('default')

            # Check if provided
            if param_name in params:
                value = params[param_name]

                # Type validation
                if param_type == 'int' and not isinstance(value, int):
                    try:
                        value = int(value)
                    except:
                        raise ValueError(
                            f"Parameter '{param_name}' must be int, got {type(value)}"
                        )

                validated[param_name] = value

            elif required:
                raise ValueError(
                    f"Required parameter '{param_name}' missing for operation '{operation_name}'"
                )

            elif default is not None:
                validated[param_name] = default

        return validated

    def _generate_chart_config(
            self,
            data: List[Dict],
            x_key: str,
            y_key: str,
            chart_type: str = "bar",
            title: str = ""
    ) -> Dict[str, Any]:
        """
        Generate Chart.js configuration for visualization

        Args:
            data: Result data
            x_key: Field to use for X axis (labels)
            y_key: Field to use for Y axis (values)
            chart_type: "bar" | "line" | "pie"
            title: Chart title

        Returns:
            Chart.js configuration object
        """
        if not data:
            return None

        labels = [str(row.get(x_key, f"Row {i}")) for i, row in enumerate(data)]
        values = [row.get(y_key, 0) for row in data]

        # Truncate labels if too long
        labels = [
            label[:30] + "..." if len(label) > 30 else label
            for label in labels
        ]

        config = {
            "type": chart_type,
            "data": {
                "labels": labels,
                "datasets": [{
                    "label": y_key.replace('_', ' ').title(),
                    "data": values,
                    "backgroundColor": "rgba(54, 162, 235, 0.6)",
                    "borderColor": "rgba(54, 162, 235, 1)",
                    "borderWidth": 1
                }]
            },
            "options": {
                "responsive": True,
                "maintainAspectRatio": False,
                "plugins": {
                    "title": {
                        "display": bool(title),
                        "text": title
                    },
                    "legend": {
                        "display": True
                    }
                },
                "scales": {
                    "y": {
                        "beginAtZero": True
                    }
                }
            }
        }

        return config

    def __repr__(self):
        return f"<{self.name} enabled={self.enabled}>"