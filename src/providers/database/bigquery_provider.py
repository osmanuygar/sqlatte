"""
BigQuery Database Provider
Supports Google Cloud BigQuery with flexible authentication options
"""

from google.cloud import bigquery
from google.oauth2 import service_account
from typing import List, Tuple, Any, Optional
import json
import os
from src.core.db_provider import DatabaseProvider


class BigQueryProvider(DatabaseProvider):
    """BigQuery database provider implementation"""

    def __init__(self, config: dict):
        super().__init__(config)

        # Required fields
        self.project_id = config.get('project_id')
        if not self.project_id:
            raise ValueError("BigQuery requires 'project_id' in configuration")

        # Optional fields
        # datasets: preferred, multi-dataset restriction. Accepts a list
        # (["ds1", "ds2"]) or a comma-separated string ("ds1, ds2").
        # dataset (singular): legacy single-dataset config, still honored.
        # Both empty -> cross-dataset mode (browse/query all datasets in project).
        raw_datasets = config.get('datasets')
        if not raw_datasets:
            legacy = config.get('dataset', '')
            raw_datasets = [legacy] if legacy else []
        elif isinstance(raw_datasets, str):
            raw_datasets = [raw_datasets]
        self.datasets: List[str] = [d.strip() for part in raw_datasets for d in part.split(',') if d.strip()]

        # Backward-compat single-dataset accessor, used as the implicit
        # default only when exactly one dataset is configured.
        self.dataset = self.datasets[0] if len(self.datasets) == 1 else ''

        self.location = config.get('location', 'US')  # Default to US multi-region

        # Authentication - 3 methods (same pattern as VertexAI)
        self.credentials_path = config.get('credentials_path')
        self.credentials_json = config.get('credentials_json')

        # Connection settings
        self.timeout = config.get('timeout', 300)  # Query timeout in seconds
        self.max_results = config.get('max_results', 10000)  # Max rows to return

        self.client = None

        # Debug logging
        print(f"\n🔍 [BigQuery] Config loaded:")
        print(f"   Project ID: {self.project_id}")
        print(f"   Dataset(s): {', '.join(self.datasets) or '(cross-dataset mode)'}")
        print(f"   Location: {self.location}")
        print(f"   Credentials: {self._get_auth_method()}")

    def _get_auth_method(self) -> str:
        """Determine which authentication method is being used"""
        if self.credentials_path:
            return f"Service Account File ({self.credentials_path})"
        elif self.credentials_json:
            return "Service Account JSON (inline)"
        else:
            return "Application Default Credentials (ADC)"

    def _get_credentials(self):
        """
        Get Google Cloud credentials using one of three methods:
        1. Service Account JSON file path
        2. Service Account JSON content (string)
        3. Application Default Credentials (for GCP environments)
        """
        # METHOD 1: credentials_path (file path)
        if self.credentials_path:
            if not os.path.exists(self.credentials_path):
                raise FileNotFoundError(
                    f"Service account file not found: {self.credentials_path}"
                )

            print(f"🔐 [BigQuery] Using credentials from file: {self.credentials_path}")
            return service_account.Credentials.from_service_account_file(
                self.credentials_path,
                scopes=["https://www.googleapis.com/auth/bigquery"]
            )

        # METHOD 2: credentials_json (JSON string)
        elif self.credentials_json:
            print(f"🔐 [BigQuery] Using inline credentials JSON")
            try:
                credentials_dict = json.loads(self.credentials_json)
                return service_account.Credentials.from_service_account_info(
                    credentials_dict,
                    scopes=["https://www.googleapis.com/auth/bigquery"]
                )
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid credentials_json format: {e}")

        # METHOD 3: Application Default Credentials (ADC)
        else:
            print(f"🔐 [BigQuery] Using Application Default Credentials (ADC)")
            # Return None - BigQuery client will use ADC automatically
            return None

    def connect(self):
        """Establish BigQuery connection"""
        try:
            credentials = self._get_credentials()

            if credentials:
                self.client = bigquery.Client(
                    project=self.project_id,
                    credentials=credentials,
                    location=self.location
                )
            else:
                # Use ADC
                self.client = bigquery.Client(
                    project=self.project_id,
                    location=self.location
                )

            print(f"✅ [BigQuery] Connection successful!")
            return self.client

        except Exception as e:
            print(f"\n❌ [BigQuery] Connection failed!")
            print(f"   Error: {str(e)}")
            raise Exception(f"BigQuery connection failed: {str(e)}")

    def get_tables(self) -> List[str]:
        """
        Get list of tables
        If one or more datasets are configured, list tables from just those
        If no datasets configured, list all tables across all datasets in the project
        """
        if not self.client:
            self.connect()

        try:
            tables = []

            if self.datasets:
                # List tables from each configured dataset
                for dataset_id in self.datasets:
                    dataset_ref = self.client.dataset(dataset_id)
                    table_list = self.client.list_tables(dataset_ref)

                    for table in table_list:
                        tables.append(f"{dataset_id}.{table.table_id}")
            else:
                # List all tables across all datasets
                datasets = list(self.client.list_datasets())

                for dataset in datasets:
                    dataset_id = dataset.dataset_id
                    dataset_ref = self.client.dataset(dataset_id)
                    table_list = self.client.list_tables(dataset_ref)

                    for table in table_list:
                        tables.append(f"{dataset_id}.{table.table_id}")

            print(f"📊 [BigQuery] Found {len(tables)} tables")
            return sorted(tables)

        except Exception as e:
            raise Exception(f"Failed to get tables: {str(e)}")

    def get_table_schema(self, table_name: str) -> str:
        """
        Get table schema with column information
        table_name can be: 'table_name' or 'dataset.table_name'
        """
        if not self.client:
            self.connect()

        try:
            # Parse table reference
            if '.' in table_name:
                parts = table_name.split('.')
                if len(parts) == 2:
                    dataset_id, table_id = parts
                elif len(parts) == 3:
                    # project.dataset.table format
                    project_id, dataset_id, table_id = parts
                else:
                    raise ValueError(f"Invalid table name format: {table_name}")
            else:
                # Use default dataset (only unambiguous when exactly one is configured)
                if len(self.datasets) != 1:
                    hint = (
                        "multiple datasets configured, specify one" if self.datasets
                        else "no default dataset configured"
                    )
                    raise ValueError(
                        f"Table name '{table_name}' requires dataset ({hint}). "
                        f"Use 'dataset.table' format."
                    )
                dataset_id = self.datasets[0]
                table_id = table_name

            # Get table reference
            table_ref = self.client.dataset(dataset_id).table(table_id)
            table = self.client.get_table(table_ref)

            # Build schema info
            schema_info = f"Table: {dataset_id}.{table_id}\n"
            schema_info += f"Description: {table.description or 'No description'}\n"
            schema_info += f"Rows: {table.num_rows:,}\n"
            schema_info += f"Size: {table.num_bytes / (1024 ** 3):.2f} GB\n"
            schema_info += f"Created: {table.created}\n"
            schema_info += f"Modified: {table.modified}\n\n"
            schema_info += "Columns:\n"

            for field in table.schema:
                mode = f" ({field.mode})" if field.mode != 'NULLABLE' else ''
                description = f" - {field.description}" if field.description else ''
                schema_info += f"  - {field.name}: {field.field_type}{mode}{description}\n"

            return schema_info

        except Exception as e:
            return f"Could not fetch schema for {table_name}: {str(e)}"

    def execute_query(self, sql: str) -> Tuple[List[str], List[List[Any]]]:
        """
        Execute SQL query and return results

        Args:
            sql: BigQuery SQL query (Standard SQL)

        Returns:
            Tuple of (column_names, rows)
        """
        if not self.client:
            self.connect()

        try:
            # Configure query job
            job_config = bigquery.QueryJobConfig(
                use_query_cache=True,
                use_legacy_sql=False,  # Force Standard SQL
            )

            # Run query
            print(f"🔍 [BigQuery] Executing query...")
            query_job = self.client.query(sql, job_config=job_config)

            # Wait for results with timeout
            results = query_job.result(timeout=self.timeout)

            # Get column names
            columns = [field.name for field in results.schema]

            # Get rows (limit to max_results)
            rows = []
            for i, row in enumerate(results):
                if i >= self.max_results:
                    print(f"⚠️  [BigQuery] Result limited to {self.max_results} rows")
                    break
                rows.append(list(row.values()))

            print(f"✅ [BigQuery] Query successful: {len(rows)} rows returned")
            return columns, rows

        except Exception as e:
            print(f"❌ [BigQuery] Query failed: {str(e)}")
            raise Exception(f"Query execution failed: {str(e)}")

    def health_check(self) -> bool:
        """
        Check BigQuery connection health
        Runs a simple query to verify connectivity and permissions
        """
        try:
            if not self.client:
                self.connect()

            # Simple query to test connection
            query = "SELECT 1 as health_check"
            job_config = bigquery.QueryJobConfig(use_legacy_sql=False)

            query_job = self.client.query(query, job_config=job_config)
            result = query_job.result(timeout=30)

            # Verify we got a result
            rows = list(result)

            print(f"✅ [BigQuery] Health check passed")
            return len(rows) > 0

        except Exception as e:
            print(f"❌ [BigQuery] Health check failed: {str(e)}")
            return False

    def get_connection_info(self) -> dict:
        """Get connection information for display purposes"""
        return {
            "type": "bigquery",
            "project_id": self.project_id,
            "datasets": self.datasets or "(cross-dataset)",
            "location": self.location,
            "auth_method": self._get_auth_method(),
            "timeout": self.timeout,
            "max_results": self.max_results
        }