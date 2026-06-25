"""
SQLatte Configuration Database Manager
☕ Barista's Recipe Book - Database Edition

Manages all platform configurations with PostgreSQL persistence:
- LLM configurations (provider, model, API keys)
- Database configurations (connection settings) - INCLUDING BIGQUERY ✅
- Email configurations (SMTP settings)
- UI configurations (themes, preferences)
- Plugin configurations

Features:
- Bootstrap from config.yaml on first run
- Runtime configuration updates
- Configuration history & audit trail
- Sensitive data encryption
- Multi-environment support
"""

import os
import json
import secrets
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from cryptography.fernet import Fernet
import base64


class ConfigDB:
    """
    Database-backed configuration manager
    Stores all configurations in PostgreSQL
    """

    def __init__(self,
                 db_host: str = "localhost",
                 db_port: int = 5432,
                 db_name: str = "sqlatte_config",
                 db_user: str = "postgres",
                 db_password: str = "",
                 encryption_key: Optional[str] = None,
                 use_memory: bool = False):
        """
        Initialize Config DB

        Args:
            db_host: PostgreSQL host
            db_port: PostgreSQL port
            db_name: Database name
            db_user: Database user
            db_password: Database password
            encryption_key: Fernet encryption key for sensitive data
            use_memory: If True, use SQLite in-memory (for testing)
        """
        self.use_memory = use_memory

        if use_memory:
            # Fallback to SQLite for development/testing
            import sqlite3
            self.conn = sqlite3.connect(":memory:", check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self.db_type = "sqlite"
        else:
            # PostgreSQL for production
            self.conn = psycopg2.connect(
                host=db_host,
                port=db_port,
                dbname=db_name,
                user=db_user,
                password=db_password,
                gssencmode="disable"  # Disable GSSAPI encryption for simplicity
            )
            self.db_type = "postgresql"

        # Encryption for sensitive values
        if encryption_key:
            self.cipher = Fernet(encryption_key.encode())
        else:
            # Generate a key if none provided (store this securely!)
            self.cipher = Fernet(Fernet.generate_key())

        self._init_tables()
        print(f"✅ ConfigDB initialized ({self.db_type})")

    def _init_tables(self):
        """Create configuration tables if they don't exist"""
        cursor = self.conn.cursor()

        # Main configurations table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS configurations (
                config_key VARCHAR(255) PRIMARY KEY,
                config_value TEXT NOT NULL,
                config_type VARCHAR(50) NOT NULL,  -- 'llm', 'database', 'email', 'ui', 'plugin'
                value_type VARCHAR(20) DEFAULT 'string',  -- 'string', 'int', 'bool', 'json'
                is_sensitive BOOLEAN DEFAULT FALSE,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_by VARCHAR(100) DEFAULT 'system'
            )
        """)

        # Configuration change history
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS config_history (
                id SERIAL PRIMARY KEY,
                config_key VARCHAR(255),
                old_value TEXT,
                new_value TEXT,
                changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                changed_by VARCHAR(100),
                reason TEXT,
                client_ip VARCHAR(50)
            )
        """)

        # Configuration snapshots (for rollback)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS config_snapshots (
                id SERIAL PRIMARY KEY,
                snapshot_name VARCHAR(255) UNIQUE,
                config_data TEXT NOT NULL,  -- JSON dump of all configs
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_by VARCHAR(100),
                description TEXT
            )
        """)

        # API tokens for MCP and programmatic access
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS api_tokens (
                id SERIAL PRIMARY KEY,
                token VARCHAR(64) UNIQUE NOT NULL,
                username VARCHAR(255) NOT NULL,
                db_config_encrypted TEXT NOT NULL,
                description VARCHAR(255),
                ttl_hours INTEGER NOT NULL DEFAULT 24,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,
                last_used_at TIMESTAMP,
                revoked BOOLEAN DEFAULT FALSE,
                daily_query_limit INTEGER DEFAULT NULL,
                queries_used_today INTEGER NOT NULL DEFAULT 0,
                usage_reset_date DATE DEFAULT CURRENT_DATE
            )
        """)

        # Migrate existing tables: add budget columns if missing
        if self.db_type == "postgresql":
            for col_def in [
                "daily_query_limit INTEGER DEFAULT NULL",
                "queries_used_today INTEGER NOT NULL DEFAULT 0",
                "usage_reset_date DATE DEFAULT CURRENT_DATE",
            ]:
                cursor.execute(
                    f"ALTER TABLE api_tokens ADD COLUMN IF NOT EXISTS {col_def}"
                )

        # MCP field masking rules
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS mcp_mask_rules (
                id SERIAL PRIMARY KEY,
                field_pattern VARCHAR(255) NOT NULL,
                strategy VARCHAR(20) NOT NULL DEFAULT 'hash',
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_by VARCHAR(100) DEFAULT 'admin'
            )
        """)

        self.conn.commit()
        cursor.close()

    def bootstrap_from_yaml(self, yaml_config: Dict[str, Any]) -> bool:
        """
        Bootstrap database from config.yaml
        Only runs if database is empty

        Args:
            yaml_config: Parsed config.yaml content

        Returns:
            True if bootstrapped, False if already has data
        """
        cursor = self.conn.cursor()

        # Check if already bootstrapped
        cursor.execute("SELECT COUNT(*) as count FROM configurations")
        if self.db_type == "postgresql":
            count = cursor.fetchone()[0]
        else:
            count = cursor.fetchone()['count']

        if count > 0:
            cursor.close()
            print("⏭️  Database already contains configurations, skipping bootstrap")
            return False

        print("🌱 Bootstrapping configurations from config.yaml...")

        # ============================================
        # Bootstrap LLM Configurations
        # ============================================
        llm_config = yaml_config.get('llm', {})
        provider = llm_config.get('provider', 'anthropic')

        self._set_config('llm.provider', provider, 'llm', 'string', False, 'Active LLM provider')

        # Provider-specific configs
        for prov in ['anthropic', 'gemini', 'vertexai']:
            prov_config = llm_config.get(prov, {})
            if prov_config:
                self._set_config(f'llm.{prov}.model', prov_config.get('model', ''), 'llm')
                self._set_config(f'llm.{prov}.api_key', prov_config.get('api_key', ''), 'llm', 'string', True)
                self._set_config(f'llm.{prov}.temperature', str(prov_config.get('temperature', 0.1)), 'llm', 'float')

                # Vertex AI specific
                if prov == 'vertexai':
                    self._set_config(f'llm.{prov}.project_id', prov_config.get('project_id', ''), 'llm')
                    self._set_config(f'llm.{prov}.location', prov_config.get('location', 'us-central1'), 'llm')
                    self._set_config(f'llm.{prov}.credentials_path', prov_config.get('credentials_path', ''), 'llm', 'string', True)

        # ============================================
        # Bootstrap Database Configurations
        # ============================================
        db_config = yaml_config.get('database', {})
        db_provider = db_config.get('provider', 'clickhouse')

        self._set_config('database.provider', db_provider, 'database', 'string', False, 'Active database provider')

        # Standard database providers
        for prov in ['clickhouse', 'trino', 'postgresql', 'mysql']:
            prov_config = db_config.get(prov, {})
            if prov_config:
                self._set_config(f'database.{prov}.host', prov_config.get('host', 'localhost'), 'database')
                self._set_config(f'database.{prov}.port', str(prov_config.get('port', 8123)), 'database', 'int')
                self._set_config(f'database.{prov}.database', prov_config.get('database', 'default'), 'database')
                self._set_config(f'database.{prov}.username', prov_config.get('username', ''), 'database')
                self._set_config(f'database.{prov}.password', prov_config.get('password', ''), 'database', 'string', True)

                # Trino-specific fields
                if prov == 'trino':
                    self._set_config(f'database.{prov}.catalog', prov_config.get('catalog', 'hive'), 'database')
                    self._set_config(f'database.{prov}.schema', prov_config.get('schema', 'default'), 'database')
                    self._set_config(f'database.{prov}.http_scheme', prov_config.get('http_scheme', 'https'), 'database')

        # ============================================
        # ✅ BIGQUERY CONFIGURATION (NEW!)
        # ============================================
        bigquery_config = db_config.get('bigquery', {})
        if bigquery_config:
            print("📊 Bootstrapping BigQuery configuration...")

            # Required: Project ID
            self._set_config('database.bigquery.project_id',
                           bigquery_config.get('project_id', ''),
                           'database', 'string', False,
                           'GCP Project ID (required)')

            # Optional: Dataset
            self._set_config('database.bigquery.dataset',
                           bigquery_config.get('dataset', ''),
                           'database', 'string', False,
                           'Default BigQuery dataset (optional)')

            # Optional: Location
            self._set_config('database.bigquery.location',
                           bigquery_config.get('location', 'US'),
                           'database', 'string', False,
                           'BigQuery location/region')

            # Sensitive: Credentials Path
            self._set_config('database.bigquery.credentials_path',
                           bigquery_config.get('credentials_path', ''),
                           'database', 'string', True,  # ← SENSITIVE!
                           'Service account JSON file path')

            # Sensitive: Credentials JSON
            self._set_config('database.bigquery.credentials_json',
                           bigquery_config.get('credentials_json', ''),
                           'database', 'string', True,  # ← SENSITIVE!
                           'Service account JSON content (inline)')

            # Performance: Timeout
            self._set_config('database.bigquery.timeout',
                           str(bigquery_config.get('timeout', 300)),
                           'database', 'int', False,
                           'Query timeout in seconds')

            # Performance: Max Results
            self._set_config('database.bigquery.max_results',
                           str(bigquery_config.get('max_results', 10000)),
                           'database', 'int', False,
                           'Maximum rows to return per query')

            print("   ✅ BigQuery configuration bootstrapped")

        # ============================================
        # Bootstrap Email Configurations
        # ============================================
        email_config = yaml_config.get('email', {})
        if email_config:
            smtp_config = email_config.get('smtp', {})
            self._set_config('email.enabled', str(email_config.get('enabled', False)), 'email', 'bool')
            self._set_config('email.smtp.host', smtp_config.get('host', ''), 'email')
            self._set_config('email.smtp.port', str(smtp_config.get('port', 587)), 'email', 'int')
            self._set_config('email.smtp.user', smtp_config.get('user', ''), 'email')
            self._set_config('email.smtp.password', smtp_config.get('password', ''), 'email', 'string', True)
            self._set_config('email.smtp.from_email', smtp_config.get('from_email', ''), 'email')
            self._set_config('email.smtp.from_name', smtp_config.get('from_name', 'SQLatte'), 'email')
            self._set_config('email.smtp.use_tls', str(smtp_config.get('use_tls', True)), 'email', 'bool')
            self._set_config('email.smtp.timeout', str(smtp_config.get('timeout', 30)), 'email', 'int')

        # ============================================
        # Bootstrap Scheduler Configurations
        # ============================================
        scheduler_config = yaml_config.get('scheduler', {})
        if scheduler_config:
            self._set_config('scheduler.enabled', str(scheduler_config.get('enabled', False)), 'scheduler', 'bool')
            self._set_config('scheduler.timezone', scheduler_config.get('timezone', 'UTC'), 'scheduler')
            self._set_config('scheduler.max_concurrent_jobs', str(scheduler_config.get('max_concurrent_jobs', 10)), 'scheduler', 'int')
            self._set_config('scheduler.job_timeout_seconds', str(scheduler_config.get('job_timeout_seconds', 300)), 'scheduler', 'int')
            self._set_config('scheduler.keep_history_days', str(scheduler_config.get('keep_history_days', 30)), 'scheduler', 'int')
            self._set_config('scheduler.max_executions_per_schedule', str(scheduler_config.get('max_executions_per_schedule', 100)), 'scheduler', 'int')
            self._set_config('scheduler.check_interval_seconds', str(scheduler_config.get('check_interval_seconds', 60)), 'scheduler', 'int')

        # ============================================
        # Bootstrap Insights Configurations
        # ============================================
        insights_config = yaml_config.get('insights', {})
        if insights_config:
            self._set_config('insights.enabled', str(insights_config.get('enabled', False)), 'insights', 'bool')
            self._set_config('insights.mode', insights_config.get('mode', 'hybrid'), 'insights')
            self._set_config('insights.max_insights', str(insights_config.get('max_insights', 3)), 'insights', 'int')
            self._set_config('insights.include_statistical', str(insights_config.get('include_statistical', True)), 'insights', 'bool')

        # ============================================
        # Bootstrap Export Configurations
        # ============================================
        export_config = yaml_config.get('export', {})
        if export_config:
            formats = export_config.get('formats', ['csv', 'excel', 'html'])
            self._set_config('export.formats', ','.join(formats), 'export')
            self._set_config('export.max_rows', str(export_config.get('max_rows', 1000)), 'export', 'int')
            self._set_config('export.max_file_size_mb', str(export_config.get('max_file_size_mb', 25)), 'export', 'int')
            self._set_config('export.filename_template', export_config.get('filename_template', '{{schedule_name}}_{{date}}_{{time}}.{{format}}'), 'export')
            # ============================================
            # Bootstrap Prompts Configurations
            # ============================================
            prompts_config = yaml_config.get('prompts', {})
            if prompts_config:
                print("📝 Bootstrapping prompts configuration...")

                self._set_config(
                    'prompts.intent_detection',
                    prompts_config.get('intent_detection', ''),
                    'prompts',
                    'text',
                    False,
                    'Prompt for determining if question requires SQL or chat'
                )

                self._set_config(
                    'prompts.barista_personality',
                    prompts_config.get('barista_personality', ''),
                    'prompts',
                    'text',
                    False,
                    'Prompt defining SQLatte chat personality'
                )

                self._set_config(
                    'prompts.sql_generation',
                    prompts_config.get('sql_generation', ''),
                    'prompts',
                    'text',
                    False,
                    'Prompt for natural language to SQL translation'
                )

                self._set_config(
                    'prompts.insights_generation',
                    prompts_config.get('insights_generation', ''),
                    'prompts',
                    'text',
                    False,
                    'Prompt for generating insights from query results'
                )

                print("   ✅ Prompts configuration bootstrapped")
        # ============================================
        # Bootstrap Plugin Configurations
        # ============================================
        plugins_config = yaml_config.get('plugins', {})
        for plugin_name, plugin_config in plugins_config.items():
            if isinstance(plugin_config, dict):
                for key, value in plugin_config.items():
                    is_sensitive = key in ['password', 'api_key', 'secret', 'token']
                    self._set_config(f'plugin.{plugin_name}.{key}', str(value), 'plugin', 'string', is_sensitive)

        self.conn.commit()
        cursor.close()

        print("✅ Bootstrap completed successfully")
        return True

    def _set_config(self,
                    key: str,
                    value: str,
                    config_type: str,
                    value_type: str = 'string',
                    is_sensitive: bool = False,
                    description: str = None):
        """Internal method to set a configuration value"""
        cursor = self.conn.cursor()

        # Encrypt sensitive values
        stored_value = value
        if is_sensitive and value:
            stored_value = self._encrypt(value)

        if self.db_type == "postgresql":
            cursor.execute("""
                INSERT INTO configurations (config_key, config_value, config_type, value_type, is_sensitive, description)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (config_key) DO UPDATE SET
                    config_value = EXCLUDED.config_value,
                    updated_at = CURRENT_TIMESTAMP
            """, (key, stored_value, config_type, value_type, is_sensitive, description))
        else:  # SQLite
            cursor.execute("""
                INSERT OR REPLACE INTO configurations 
                (config_key, config_value, config_type, value_type, is_sensitive, description)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (key, stored_value, config_type, value_type, is_sensitive, description))

        cursor.close()

    def get_config(self, key: str, default: Any = None, decrypt: bool = True) -> Any:
        """
        Get a configuration value

        Args:
            key: Configuration key (e.g., 'llm.anthropic.api_key')
            default: Default value if not found
            decrypt: If True, decrypt sensitive values

        Returns:
            Configuration value (auto-typed)
        """
        if self.db_type == "postgresql":
            cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        else:
            cursor = self.conn.cursor()

        if self.db_type == "postgresql":
            cursor.execute(
                "SELECT config_value, value_type, is_sensitive FROM configurations WHERE config_key = %s",
                (key,)
            )
        else:
            cursor.execute(
                "SELECT config_value, value_type, is_sensitive FROM configurations WHERE config_key = ?",
                (key,)
            )

        row = cursor.fetchone()
        cursor.close()

        if not row:
            return default

        if self.db_type == "postgresql":
            value = row['config_value']
            value_type = row['value_type']
            is_sensitive = row['is_sensitive']
        else:
            value = row['config_value']
            value_type = row['value_type']
            is_sensitive = row['is_sensitive']

        # Decrypt if sensitive and requested
        if is_sensitive and decrypt:
            value = self._decrypt(value)

        # Type conversion
        if value_type == 'int':
            return int(value) if value else default
        elif value_type == 'float':
            return float(value) if value else default
        elif value_type == 'bool':
            return value.lower() == 'true' if value else default
        elif value_type == 'json':
            return json.loads(value) if value else default
        else:
            return value if value else default

    def set_config(self,
                   key: str,
                   value: Any,
                   user: str = 'system',
                   reason: str = None,
                   client_ip: str = None) -> bool:
        """
        Update a configuration value with history tracking

        Args:
            key: Configuration key
            value: New value
            user: User making the change
            reason: Reason for change
            client_ip: Client IP address

        Returns:
            True if successful
        """
        if self.db_type == "postgresql":
            cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        else:
            cursor = self.conn.cursor()

        # Get current value for history
        old_value = self.get_config(key, decrypt=False)

        # Get metadata
        if self.db_type == "postgresql":
            cursor.execute(
                "SELECT value_type, is_sensitive FROM configurations WHERE config_key = %s",
                (key,)
            )
        else:
            cursor.execute(
                "SELECT value_type, is_sensitive FROM configurations WHERE config_key = ?",
                (key,)
            )

        row = cursor.fetchone()

        if not row:
            cursor.close()
            raise ValueError(f"Configuration key '{key}' not found")

        if self.db_type == "postgresql":
            value_type = row['value_type']
            is_sensitive = row['is_sensitive']
        else:
            value_type = row['value_type']
            is_sensitive = row['is_sensitive']

        # Convert value to string
        stored_value = str(value)

        # Encrypt if sensitive
        if is_sensitive:
            stored_value = self._encrypt(stored_value)

        # Update configuration
        if self.db_type == "postgresql":
            cursor.execute("""
                UPDATE configurations 
                SET config_value = %s, updated_at = CURRENT_TIMESTAMP, updated_by = %s
                WHERE config_key = %s
            """, (stored_value, user, key))
        else:
            cursor.execute("""
                UPDATE configurations 
                SET config_value = ?, updated_at = CURRENT_TIMESTAMP, updated_by = ?
                WHERE config_key = ?
            """, (stored_value, user, key))

        # Record history
        if old_value != stored_value:
            if self.db_type == "postgresql":
                cursor.execute("""
                    INSERT INTO config_history (config_key, old_value, new_value, changed_by, reason, client_ip)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (key, old_value or '', stored_value, user, reason, client_ip))
            else:
                cursor.execute("""
                    INSERT INTO config_history (config_key, old_value, new_value, changed_by, reason, client_ip)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (key, old_value or '', stored_value, user, reason, client_ip))

        self.conn.commit()
        cursor.close()

        print(f"✅ Config updated: {key} = {value if not is_sensitive else '***'} (by {user})")
        return True

    def get_all_configs(self,
                        config_type: Optional[str] = None,
                        include_sensitive: bool = False,
                        decrypt_sensitive: bool = False) -> Dict[str, Any]:
        """
        Get all configurations, optionally filtered by type

        Args:
            config_type: Filter by type ('llm', 'database', 'email', etc.)
            include_sensitive: If True, include sensitive fields
            decrypt_sensitive: If True, decrypt sensitive values

        Returns:
            Dictionary of all configurations
        """
        if self.db_type == "postgresql":
            cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        else:
            cursor = self.conn.cursor()

        query = "SELECT config_key, config_value, value_type, is_sensitive FROM configurations"
        params = None

        if config_type:
            query += " WHERE config_type = ?"
            params = (config_type,)
            if self.db_type == "postgresql":
                query = query.replace("?", "%s")

        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)

        configs = {}
        for row in cursor.fetchall():
            if self.db_type == "postgresql":
                key = row['config_key']
                value = row['config_value']
                value_type = row['value_type']
                is_sensitive = row['is_sensitive']
            else:
                key = row['config_key']
                value = row['config_value']
                value_type = row['value_type']
                is_sensitive = row['is_sensitive']

            # Skip sensitive if not requested
            if is_sensitive and not include_sensitive:
                continue

            # Decrypt if requested
            if is_sensitive and decrypt_sensitive:
                value = self._decrypt(value)

            # Type conversion
            if value_type == 'int':
                value = int(value) if value else 0
            elif value_type == 'float':
                value = float(value) if value else 0.0
            elif value_type == 'bool':
                value = value.lower() == 'true' if value else False
            elif value_type == 'json':
                value = json.loads(value) if value else {}

            configs[key] = value

        cursor.close()
        return configs

    def get_config_history(self, key: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """Get configuration change history"""
        if self.db_type == "postgresql":
            cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        else:
            cursor = self.conn.cursor()

        if key:
            query = "SELECT * FROM config_history WHERE config_key = ? ORDER BY changed_at DESC LIMIT ?"
            params = (key, limit)
            if self.db_type == "postgresql":
                query = query.replace("?", "%s")
            cursor.execute(query, params)
        else:
            query = "SELECT * FROM config_history ORDER BY changed_at DESC LIMIT ?"
            params = (limit,)
            if self.db_type == "postgresql":
                query = query.replace("?", "%s")
            cursor.execute(query, params)

        history = []
        for row in cursor.fetchall():
            history.append(dict(row))

        cursor.close()
        return history

    def create_snapshot(self, snapshot_name: str, user: str = 'system', description: str = None) -> bool:
        """Create a configuration snapshot"""
        all_configs = self.get_all_configs(include_sensitive=True, decrypt_sensitive=False)
        config_data = json.dumps(all_configs)

        cursor = self.conn.cursor()

        if self.db_type == "postgresql":
            cursor.execute("""
                INSERT INTO config_snapshots (snapshot_name, config_data, created_by, description)
                VALUES (%s, %s, %s, %s)
            """, (snapshot_name, config_data, user, description))
        else:
            cursor.execute("""
                INSERT INTO config_snapshots (snapshot_name, config_data, created_by, description)
                VALUES (?, ?, ?, ?)
            """, (snapshot_name, config_data, user, description))

        self.conn.commit()
        cursor.close()

        print(f"📸 Snapshot created: {snapshot_name}")
        return True

    def restore_snapshot(self, snapshot_name: str, user: str = 'system') -> bool:
        """Restore configuration from a snapshot"""
        if self.db_type == "postgresql":
            cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        else:
            cursor = self.conn.cursor()

        if self.db_type == "postgresql":
            cursor.execute(
                "SELECT config_data FROM config_snapshots WHERE snapshot_name = %s",
                (snapshot_name,)
            )
        else:
            cursor.execute(
                "SELECT config_data FROM config_snapshots WHERE snapshot_name = ?",
                (snapshot_name,)
            )

        row = cursor.fetchone()

        if not row:
            cursor.close()
            raise ValueError(f"Snapshot '{snapshot_name}' not found")

        if self.db_type == "postgresql":
            config_data = json.loads(row['config_data'])
        else:
            config_data = json.loads(row['config_data'])

        # Restore each configuration
        for key, value in config_data.items():
            self.set_config(key, value, user=user, reason=f"Restored from snapshot: {snapshot_name}")

        cursor.close()
        print(f"♻️  Snapshot restored: {snapshot_name}")
        return True

    def _encrypt(self, value: str) -> str:
        """Encrypt sensitive value"""
        if not value:
            return value
        return self.cipher.encrypt(value.encode()).decode()

    def _decrypt(self, value: str) -> str:
        """Decrypt sensitive value. Raises RuntimeError on failure instead of leaking ciphertext."""
        if not value:
            return value
        try:
            return self.cipher.decrypt(value.encode()).decode()
        except Exception as e:
            raise RuntimeError(
                "Decryption failed — the encryption key may have changed or the value is corrupt. "
                "Set a stable ENCRYPTION_KEY and re-save affected config values."
            ) from e

    # ============================================
    # API Token Management
    # ============================================

    def get_default_token_limit(self) -> Optional[int]:
        """Return the platform-wide default daily query limit for new tokens (None = unlimited)."""
        raw = self.get_config("tokens.default_daily_limit", default=None)
        if raw is None:
            return None
        try:
            return int(raw)
        except (ValueError, TypeError):
            return None

    def set_default_token_limit(self, limit: Optional[int], changed_by: str = "admin") -> None:
        """Set the platform-wide default daily query limit (None clears it → unlimited)."""
        if limit is None:
            self._set_config("tokens.default_daily_limit", "", "tokens", "int", False,
                             "Default daily query limit per API token (empty = unlimited)")
        else:
            self._set_config("tokens.default_daily_limit", str(int(limit)), "tokens", "int", False,
                             "Default daily query limit per API token (empty = unlimited)")

    def admin_set_token_limit(self, token_id: int, limit: Optional[int]) -> bool:
        """Override daily query limit on a specific token by DB id (admin only). None = unlimited."""
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE api_tokens SET daily_query_limit = %s WHERE id = %s",
            (limit, token_id)
        )
        affected = cursor.rowcount
        self.conn.commit()
        cursor.close()
        return affected > 0

    def create_api_token(
        self,
        username: str,
        db_config: Dict[str, Any],
        ttl_hours: int = 24,
        description: str = "MCP Token",
        daily_query_limit: Optional[int] = None,
    ) -> str:
        """Create a persisted API token storing encrypted db_config.

        daily_query_limit: queries per day cap; None → inherit platform default.
        If a platform default exists and the caller passes a higher value, the
        platform default wins (user cannot exceed the admin-set ceiling).
        """
        platform_default = self.get_default_token_limit()

        if daily_query_limit is None:
            effective_limit = platform_default
        elif platform_default is not None:
            effective_limit = min(daily_query_limit, platform_default)
        else:
            effective_limit = daily_query_limit

        token = secrets.token_urlsafe(48)
        db_config_json = json.dumps(db_config)
        encrypted = self._encrypt(db_config_json)
        expires_at = datetime.now() + timedelta(hours=ttl_hours)

        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO api_tokens
                (token, username, db_config_encrypted, description, ttl_hours, expires_at, daily_query_limit)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (token, username, encrypted, description, ttl_hours, expires_at, effective_limit)
        )
        self.conn.commit()
        cursor.close()
        limit_str = f"{effective_limit}/day" if effective_limit is not None else "unlimited"
        print(f"🔑 API token created for {username} (TTL: {ttl_hours}h, limit: {limit_str})")
        return token

    def validate_api_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Validate token and return token data or None.

        Returns:
          None                             — invalid / expired / revoked
          {"_error": "budget_exceeded", …} — token is valid but daily limit hit
          {"username": …, "db_config": …}  — success
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT username, db_config_encrypted, expires_at, revoked,
                   daily_query_limit, queries_used_today, usage_reset_date
            FROM api_tokens WHERE token = %s
            """,
            (token,)
        )
        row = cursor.fetchone()
        if not row:
            cursor.close()
            return None

        username, encrypted, expires_at, revoked = row[0], row[1], row[2], row[3]
        daily_limit, queries_used_today, usage_reset_date = row[4], row[5], row[6]

        if revoked:
            cursor.close()
            return None

        if datetime.now() > expires_at:
            cursor.close()
            return None

        today = datetime.now().date()

        # Reset daily counter when the calendar date has rolled over
        if usage_reset_date != today:
            cursor.execute(
                "UPDATE api_tokens SET queries_used_today = 0, usage_reset_date = %s WHERE token = %s",
                (today, token)
            )
            self.conn.commit()
            queries_used_today = 0

        # Enforce per-token daily budget
        if daily_limit is not None and queries_used_today >= daily_limit:
            cursor.close()
            return {
                "_error": "budget_exceeded",
                "daily_limit": daily_limit,
                "queries_used_today": queries_used_today,
            }

        cursor.execute(
            "UPDATE api_tokens SET last_used_at = %s, queries_used_today = queries_used_today + 1 WHERE token = %s",
            (datetime.now(), token)
        )
        self.conn.commit()
        cursor.close()

        db_config = json.loads(self._decrypt(encrypted))
        return {"username": username, "db_config": db_config}

    def revoke_api_token(self, token: str, username: str) -> bool:
        """Revoke a token (only owner can revoke)."""
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE api_tokens SET revoked = TRUE WHERE token = %s AND username = %s",
            (token, username)
        )
        affected = cursor.rowcount
        self.conn.commit()
        cursor.close()
        return affected > 0

    def list_api_tokens(self, username: str) -> List[Dict[str, Any]]:
        """List all active (non-revoked, non-expired) tokens for a user."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT token, description, ttl_hours, created_at, expires_at, last_used_at,
                   daily_query_limit, queries_used_today, usage_reset_date
            FROM api_tokens
            WHERE username = %s AND revoked = FALSE AND expires_at > %s
            ORDER BY created_at DESC
            """,
            (username, datetime.now())
        )
        rows = cursor.fetchall()
        cursor.close()
        today = datetime.now().date()
        return [
            {
                "token_prefix": row[0][:12] + "...",
                "description": row[1],
                "ttl_hours": row[2],
                "created_at": row[3].isoformat() if row[3] else None,
                "expires_at": row[4].isoformat() if row[4] else None,
                "last_used_at": row[5].isoformat() if row[5] else None,
                "daily_query_limit": row[6],
                "queries_used_today": row[7] if row[8] == today else 0,
            }
            for row in rows
        ]

    def list_all_api_tokens(self) -> list:
        """List all tokens across all users (admin use)."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT id, token, username, description, ttl_hours, created_at, expires_at,
                   last_used_at, revoked, daily_query_limit, queries_used_today, usage_reset_date
            FROM api_tokens
            ORDER BY created_at DESC
            """
        )
        rows = cursor.fetchall()
        cursor.close()
        now = datetime.now()
        today = now.date()
        return [
            {
                "id": row[0],
                "token_prefix": row[1][:12] + "...",
                # Full token intentionally omitted — write-once, shown at creation only.
                "username": row[2],
                "description": row[3],
                "ttl_hours": row[4],
                "created_at": row[5].isoformat() if row[5] else None,
                "expires_at": row[6].isoformat() if row[6] else None,
                "last_used_at": row[7].isoformat() if row[7] else None,
                "revoked": bool(row[8]),
                "expired": row[6] is not None and now > row[6],
                "daily_query_limit": row[9],
                "queries_used_today": row[10] if row[11] == today else 0,
            }
            for row in rows
        ]

    def admin_revoke_token(self, token_id: int) -> bool:
        """Revoke any token by its DB id (admin only). Accepts integer id, not the token value."""
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE api_tokens SET revoked = TRUE WHERE id = %s",
            (token_id,)
        )
        affected = cursor.rowcount
        self.conn.commit()
        cursor.close()
        return affected > 0

    # ── MCP Mask Rules ────────────────────────────────────────────────────────

    def list_mask_rules(self) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT id, field_pattern, strategy, enabled, description, created_at, updated_at, created_by "
            "FROM mcp_mask_rules ORDER BY id"
        )
        rows = cursor.fetchall()
        cursor.close()
        keys = ["id", "field_pattern", "strategy", "enabled", "description", "created_at", "updated_at", "created_by"]
        return [dict(zip(keys, r)) for r in rows]

    def create_mask_rule(self, field_pattern: str, strategy: str, description: str = "", created_by: str = "admin") -> Dict[str, Any]:
        if strategy not in ("hash", "partial", "redact"):
            raise ValueError(f"Invalid strategy: {strategy}")
        cursor = self.conn.cursor()
        if self.db_type == "postgresql":
            cursor.execute(
                "INSERT INTO mcp_mask_rules (field_pattern, strategy, description, created_by) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                (field_pattern.lower().strip(), strategy, description, created_by)
            )
            row_id = cursor.fetchone()[0]
        else:
            cursor.execute(
                "INSERT INTO mcp_mask_rules (field_pattern, strategy, description, created_by) VALUES (?,?,?,?)",
                (field_pattern.lower().strip(), strategy, description, created_by)
            )
            row_id = cursor.lastrowid
        self.conn.commit()
        cursor.close()
        return {"id": row_id, "field_pattern": field_pattern, "strategy": strategy, "enabled": True, "description": description}

    def update_mask_rule(self, rule_id: int, field_pattern: str = None, strategy: str = None,
                         enabled: bool = None, description: str = None) -> bool:
        fields, values = [], []
        if field_pattern is not None:
            fields.append("field_pattern = %s" if self.db_type == "postgresql" else "field_pattern = ?")
            values.append(field_pattern.lower().strip())
        if strategy is not None:
            if strategy not in ("hash", "partial", "redact"):
                raise ValueError(f"Invalid strategy: {strategy}")
            fields.append("strategy = %s" if self.db_type == "postgresql" else "strategy = ?")
            values.append(strategy)
        if enabled is not None:
            fields.append("enabled = %s" if self.db_type == "postgresql" else "enabled = ?")
            values.append(enabled)
        if description is not None:
            fields.append("description = %s" if self.db_type == "postgresql" else "description = ?")
            values.append(description)
        if not fields:
            return False
        fields.append("updated_at = CURRENT_TIMESTAMP")
        ph = "%s" if self.db_type == "postgresql" else "?"
        values.append(rule_id)
        cursor = self.conn.cursor()
        cursor.execute(f"UPDATE mcp_mask_rules SET {', '.join(fields)} WHERE id = {ph}", values)
        affected = cursor.rowcount
        self.conn.commit()
        cursor.close()
        return affected > 0

    def delete_mask_rule(self, rule_id: int) -> bool:
        ph = "%s" if self.db_type == "postgresql" else "?"
        cursor = self.conn.cursor()
        cursor.execute(f"DELETE FROM mcp_mask_rules WHERE id = {ph}", (rule_id,))
        affected = cursor.rowcount
        self.conn.commit()
        cursor.close()
        return affected > 0

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            print("✅ ConfigDB connection closed")


# ============================================
# Singleton Instance
# ============================================

_config_db_instance = None


def get_config_db(config: dict = None, use_memory: bool = False) -> ConfigDB:
    """
    Get singleton ConfigDB instance

    Args:
        config: Configuration dict (from config.yaml)
        use_memory: If True, use SQLite in-memory (for testing)
    """
    global _config_db_instance

    if _config_db_instance is None:
        # Priority: config.yaml > environment variables > defaults

        if config and 'config_db' in config:
            # Use config.yaml settings
            config_db_config = config['config_db']

            if config_db_config.get('type') == 'postgresql':
                pg_config = config_db_config.get('postgresql', {})
                db_host = pg_config.get('host', 'localhost')
                db_port = pg_config.get('port', 5432)
                db_name = pg_config.get('database', 'sqlatte_config')
                db_user = pg_config.get('user', 'postgres')
                db_password = pg_config.get('password', '')
            else:
                # SQLite or defaults
                db_host = 'localhost'
                db_port = 5432
                db_name = 'sqlatte_config'
                db_user = 'postgres'
                db_password = ''

            encryption_key = config_db_config.get('encryption_key')
        else:
            # Fallback to environment variables
            db_host = os.getenv('CONFIG_DB_HOST', 'localhost')
            db_port = int(os.getenv('CONFIG_DB_PORT', '5432'))
            db_name = os.getenv('CONFIG_DB_NAME', 'sqlatte_config')
            db_user = os.getenv('CONFIG_DB_USER', 'postgres')
            db_password = os.getenv('CONFIG_DB_PASSWORD', '')
            encryption_key = os.getenv('CONFIG_ENCRYPTION_KEY')

        _config_db_instance = ConfigDB(
            db_host=db_host,
            db_port=db_port,
            db_name=db_name,
            db_user=db_user,
            db_password=db_password,
            encryption_key=encryption_key,
            use_memory=use_memory
        )

    return _config_db_instance