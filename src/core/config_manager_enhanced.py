"""
SQLatte Config Manager - Enhanced with Database Support
Allows config updates without restart, with optional PostgreSQL persistence
"""

import os
import yaml
import threading
from typing import Dict, Any, Optional
from copy import deepcopy


class ConfigManager:
    """
    Singleton Config Manager with Database Support

    Features:
    - Loads config from YAML on startup
    - Optional PostgreSQL persistence for runtime updates
    - Thread-safe config updates
    - Configuration history and snapshots
    - Runtime provider reload without restart

    Config Priority (highest to lowest):
    1. Runtime overrides (in-memory)
    2. Database configurations (if enabled)
    3. YAML file configurations
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, 'initialized'):
            self.config: Dict[str, Any] = {}
            self.config_path: Optional[str] = None
            self.runtime_overrides: Dict[str, Any] = {}
            self._config_lock = threading.RLock()
            self.config_db = None
            self.db_enabled = False
            self.initialized = True

    def load_from_file(self, config_path: str, enable_db: bool = False) -> Dict[str, Any]:
        """
        Load initial config from YAML file

        Args:
            config_path: Path to config.yaml
            enable_db: If True, enable database-backed config storage
        """
        self.config_path = config_path

        with open(config_path, 'r') as f:
            file_config = yaml.safe_load(f)

        # Resolve environment variables
        from src.core.config_loader import ConfigLoader
        resolved_config = ConfigLoader._resolve_env_vars(file_config)

        with self._config_lock:
            self.config = resolved_config

        print(f"✅ Config loaded from: {config_path}")

        # Initialize database backend if enabled
        if enable_db:
            self._init_config_db(resolved_config)

        return self.get_config()

    def _init_config_db(self, yaml_config: Dict[str, Any]):
        """Initialize database backend for configuration storage"""
        try:
            from src.core.config_db import get_config_db

            # Check config.yaml for config_db settings
            config_db_config = yaml_config.get('config_db', {})
            config_db_enabled = config_db_config.get('enabled', False)

            # Also check environment variable (backwards compatibility)
            env_enabled = os.getenv('CONFIG_DB_ENABLED', 'false').lower() == 'true'

            if config_db_enabled or env_enabled:
                # Determine if using memory or PostgreSQL
                db_type = config_db_config.get('type', 'postgresql')
                use_memory = (db_type == 'sqlite')

                # Pass the full config to get_config_db
                self.config_db = get_config_db(config=yaml_config, use_memory=use_memory)
                self.db_enabled = True

                # Bootstrap from YAML if DB is empty
                self.config_db.bootstrap_from_yaml(yaml_config)
                # Ensure newly introduced semantic layer keys exist on every startup
                self.config_db.ensure_semantic_layer_configs(yaml_config)

                print(f"✅ Database-backed configuration enabled ({db_type.upper()})")
            else:
                # Fallback: try in-memory mode for development
                self.config_db = get_config_db(config=yaml_config, use_memory=True)
                self.db_enabled = True

                # Bootstrap from YAML
                self.config_db.bootstrap_from_yaml(yaml_config)
                # Keep semantic layer keyset in sync each run
                self.config_db.ensure_semantic_layer_configs(yaml_config)

                print("✅ Database-backed configuration enabled (In-Memory SQLite)")

        except Exception as e:
            print(f"⚠️  Could not initialize config database: {e}")
            print("   Falling back to YAML-only mode")
            self.config_db = None
            self.db_enabled = False

    def get_config(self) -> Dict[str, Any]:
        """
        Get current active configuration

        Priority:
        1. Runtime overrides (in-memory)
        2. Database configurations (if enabled)
        3. YAML file configurations
        """
        with self._config_lock:
            # Start with file config
            merged = deepcopy(self.config)

            # Overlay database config if enabled
            if self.db_enabled and self.config_db:
                db_configs = self.config_db.get_all_configs(include_sensitive=True, decrypt_sensitive=True)
                merged = self._merge_flat_to_nested(merged, db_configs)

            # Apply runtime overrides
            self._deep_merge(merged, self.runtime_overrides)

            return merged

    def _merge_flat_to_nested(self, base: Dict[str, Any], flat_configs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merge flat database configs (e.g., 'llm.anthropic.api_key')
        into nested dictionary structure
        """
        for key, value in flat_configs.items():
            keys = key.split('.')
            current = base

            # Navigate to the correct nested level
            for k in keys[:-1]:
                if k not in current:
                    current[k] = {}
                current = current[k]

            # Set the value
            current[keys[-1]] = value

        return base

    def get_safe_config(self) -> Dict[str, Any]:
        """Get config with sensitive data masked"""
        config = self.get_config()
        safe_config = deepcopy(config)

        # Mask sensitive fields
        sensitive_fields = ['api_key', 'password', 'credentials_json', 'credentials_path', 'secret_key',
        'token']

        def mask_recursive(obj):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if key in sensitive_fields and value:
                        obj[key] = self._mask_sensitive(str(value))
                    elif isinstance(value, (dict, list)):
                        mask_recursive(value)
            elif isinstance(obj, list):
                for item in obj:
                    mask_recursive(item)

        mask_recursive(safe_config)
        return safe_config

    def update_config(
        self,
        updates: Dict[str, Any],
        persist: bool = False,
        user: str = 'system',
        reason: str = None
    ) -> Dict[str, Any]:
        """
        Update configuration at runtime

        Args:
            updates: Configuration updates (nested dict)
            persist: If True, save to database (if enabled) or YAML file
            user: User making the change (for audit trail)
            reason: Reason for the change

        Returns:
            Updated configuration
        """
        with self._config_lock:
            if persist and self.db_enabled and self.config_db:
                # Save to database
                flat_updates = self._flatten_dict(updates)
                for key, value in flat_updates.items():
                    try:
                        self.config_db.set_config(key, value, user=user, reason=reason)
                    except ValueError:
                        # Key doesn't exist in DB, skip
                        print(f"⚠️  Config key '{key}' not found in database, skipping")
                        pass

                print(f"✅ Configuration persisted to database by {user}")
            elif persist and self.config_path:
                # Apply updates to runtime overrides first
                self._deep_merge(self.runtime_overrides, updates)
                # Save to file
                self._save_to_file()
            else:
                # Just apply to runtime overrides (not persisted)
                self._deep_merge(self.runtime_overrides, updates)

            return self.get_config()

    def _flatten_dict(self, nested: Dict[str, Any], parent_key: str = '', sep: str = '.') -> Dict[str, Any]:
        """Flatten nested dictionary to dot-notation keys"""
        items = []
        for k, v in nested.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(self._flatten_dict(v, new_key, sep=sep).items())
            else:
                items.append((new_key, v))
        return dict(items)

    def update_llm_config(
        self,
        provider: str,
        provider_config: Dict[str, Any],
        persist: bool = False,
        user: str = 'system'
    ) -> Dict[str, Any]:
        """
        Update LLM provider configuration

        IMPORTANT: Preserves original api_key if masked value is sent
        """
        # 🔒 API_KEY FIX: If api_key is masked, use existing api_key
        if 'api_key' in provider_config:
            if provider_config['api_key'] == '***masked***' or not provider_config['api_key']:
                # Get current config
                current_config = self.get_config()
                current_llm_config = current_config.get('llm', {}).get(provider, {})

                if 'api_key' in current_llm_config:
                    print(f"🔒 [ConfigManager] API key masked, preserving original value")
                    provider_config['api_key'] = current_llm_config['api_key']
                else:
                    # No existing api_key, remove the masked value
                    print(f"⚠️  [ConfigManager] No existing API key, removing masked value")
                    provider_config.pop('api_key', None)

        updates = {
            'llm': {
                'provider': provider,
                provider: provider_config
            }
        }
        return self.update_config(updates, persist=persist, user=user, reason=f"LLM config updated: {provider}")

    def update_database_config(
        self,
        provider: str,
        provider_config: Dict[str, Any],
        persist: bool = False,
        user: str = 'system'
    ) -> Dict[str, Any]:
        """
        Update Database provider configuration

        IMPORTANT: Preserves original password if masked value is sent
        """
        # 🔒 PASSWORD FIX: If password is masked, use existing password
        if 'password' in provider_config:
            if provider_config['password'] == '***masked***' or not provider_config['password']:
                # Get current config
                current_config = self.get_config()
                current_db_config = current_config.get('database', {}).get(provider, {})

                if 'password' in current_db_config:
                    print(f"🔒 [ConfigManager] Password masked, preserving original value")
                    provider_config['password'] = current_db_config['password']
                else:
                    # No existing password, remove the masked value
                    print(f"⚠️  [ConfigManager] No existing password, removing masked value")
                    provider_config.pop('password', None)

        if provider == 'bigquery':
            # Handle credentials_path
            if 'credentials_path' in provider_config:
                if provider_config['credentials_path'] == '***masked***' or not provider_config['credentials_path']:
                    if 'credentials_path' in current_db_config:
                        print(f"🔒 [ConfigManager] BigQuery credentials_path masked, preserving original")
                        provider_config['credentials_path'] = current_db_config['credentials_path']
                    else:
                        print(f"⚠️  [ConfigManager] No existing credentials_path, removing masked value")
                        provider_config.pop('credentials_path', None)

            # Handle credentials_json
            if 'credentials_json' in provider_config:
                if provider_config['credentials_json'] == '***masked***' or not provider_config['credentials_json']:
                    if 'credentials_json' in current_db_config:
                        print(f"🔒 [ConfigManager] BigQuery credentials_json masked, preserving original")
                        provider_config['credentials_json'] = current_db_config['credentials_json']
                    else:
                        print(f"⚠️  [ConfigManager] No existing credentials_json, removing masked value")
                        provider_config.pop('credentials_json', None)

            # Project ID should NOT be masked, but check for empty values
            if 'project_id' in provider_config:
                if not provider_config['project_id'] or provider_config['project_id'] == '***masked***':
                    if 'project_id' in current_db_config:
                        print(f"🔒 [ConfigManager] BigQuery project_id empty, preserving original")
                        provider_config['project_id'] = current_db_config['project_id']

        updates = {
            'database': {
                'provider': provider,
                provider: provider_config
            }
        }
        return self.update_config(updates, persist=persist, user=user, reason=f"Database config updated: {provider}")

    def update_email_config(
        self,
        email_config: Dict[str, Any],
        persist: bool = False,
        user: str = 'system'
    ) -> Dict[str, Any]:
        """Update email configuration"""
        # 🔒 PASSWORD FIX: Preserve SMTP password if masked
        if 'smtp' in email_config and 'password' in email_config['smtp']:
            if email_config['smtp']['password'] == '***masked***' or not email_config['smtp']['password']:
                current_config = self.get_config()
                current_smtp = current_config.get('email', {}).get('smtp', {})
                if 'password' in current_smtp:
                    email_config['smtp']['password'] = current_smtp['password']
                else:
                    email_config['smtp'].pop('password', None)

        updates = {'email': email_config}
        return self.update_config(updates, persist=persist, user=user, reason="Email config updated")

    def get_config_history(self, key: Optional[str] = None, limit: int = 100) -> list:
        """
        Get configuration change history from database

        Args:
            key: Specific config key (None for all)
            limit: Maximum number of records

        Returns:
            List of history records (empty if DB not enabled)
        """
        if self.db_enabled and self.config_db:
            return self.config_db.get_config_history(key=key, limit=limit)
        return []

    def create_snapshot(self, snapshot_name: str, user: str = 'system', description: str = None) -> bool:
        """
        Create a configuration snapshot

        Args:
            snapshot_name: Name of the snapshot
            user: User creating the snapshot
            description: Optional description

        Returns:
            True if successful, False if DB not enabled
        """
        if self.db_enabled and self.config_db:
            return self.config_db.create_snapshot(snapshot_name, user=user, description=description)
        print("⚠️  Snapshots require database-backed configuration")
        return False

    def restore_snapshot(self, snapshot_name: str, user: str = 'system') -> bool:
        """
        Restore configuration from a snapshot

        Args:
            snapshot_name: Name of the snapshot to restore
            user: User performing the restore

        Returns:
            True if successful, False if DB not enabled
        """
        if self.db_enabled and self.config_db:
            success = self.config_db.restore_snapshot(snapshot_name, user=user)
            if success:
                # Clear runtime overrides after restore
                with self._config_lock:
                    self.runtime_overrides = {}
            return success
        print("⚠️  Snapshots require database-backed configuration")
        return False

    def reset_to_file(self):
        """Reset runtime overrides, reload from file"""
        with self._config_lock:
            self.runtime_overrides = {}

            if self.config_path:
                self.load_from_file(self.config_path, enable_db=self.db_enabled)

        print("🔄 Config reset to file defaults")
        return self.get_config()

    def _deep_merge(self, base: dict, updates: dict):
        """Deep merge updates into base dict"""
        for key, value in updates.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value

    def _mask_sensitive(self, value: str) -> str:
        if not value:
            return ''
        return '***masked***'  # karakter sayısı bile belli olmasın

    def _save_to_file(self):
        """Save current config to YAML file"""
        if not self.config_path:
            return

        merged_config = self.get_config()

        with open(self.config_path, 'w') as f:
            yaml.dump(merged_config, f, default_flow_style=False)

        print(f"✅ Config saved to: {self.config_path}")

    def test_connection(
        self,
        provider_type: str,
        provider: str,
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Test a provider configuration before applying

        Args:
            provider_type: 'llm' or 'database'
            provider: Provider name
            config: Provider configuration

        Returns:
            Test result dict with 'success' and 'message'
        """
        if provider_type == 'llm':
            return self._test_llm(provider, config)
        elif provider_type == 'database':
            return self._test_database(provider, config)
        else:
            return {
                'success': False,
                'message': f'Unknown provider type: {provider_type}'
            }

    def _test_llm(self, provider: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """Test LLM provider connection"""
        from src.core.provider_factory import ProviderFactory

        test_config = {
            'llm': {
                'provider': provider,
                provider: config
            }
        }

        try:
            llm_provider = ProviderFactory.create_llm_provider(test_config)
            is_healthy = llm_provider.health_check()

            return {
                'success': is_healthy,
                'message': 'Connection successful' if is_healthy else 'Connection failed',
                'provider': provider,
                'model': llm_provider.get_model_name()
            }
        except Exception as e:
            return {
                'success': False,
                'message': f'Connection failed: {str(e)}'
            }

    def _test_database(self, provider: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """Test Database provider connection WITH ENHANCED LOGGING"""
        from src.core.provider_factory import ProviderFactory

        test_config = {
            'database': {
                'provider': provider,
                provider: config
            }
        }

        print(f"🔌 [TEST DB] Creating {provider} provider instance...")
        print(f"   Using config:")
        for key, value in config.items():
            if 'password' in key.lower():
                print(f"      {key}: {'*' * len(str(value)) if value else '(empty)'}")
            else:
                print(f"      {key}: {value}")

        try:
            db_provider = ProviderFactory.create_db_provider(test_config)

            print(f"🏥 [TEST DB] Running health check...")
            is_healthy = db_provider.health_check()

            tables = []
            if is_healthy:
                try:
                    print(f"📊 [TEST DB] Fetching table list...")
                    tables = db_provider.get_tables()
                    print(f"✅ [TEST DB] Found {len(tables)} tables")
                except Exception as table_error:
                    print(f"⚠️  [TEST DB] Could not fetch tables: {table_error}")
                    pass

            print(f"{'✅' if is_healthy else '❌'} [TEST DB] Final result: {is_healthy}")

            return {
                'success': is_healthy,
                'message': 'Connection successful' if is_healthy else 'Connection failed',
                'provider': provider,
                'connection_info': db_provider.get_connection_info(),
                'table_count': len(tables)
            }
        except Exception as e:
            print(f"❌ [TEST DB] Exception occurred: {e}")
            import traceback
            traceback.print_exc()

            return {
                'success': False,
                'message': f'Connection failed: {str(e)}'
            }


# Global singleton instance
config_manager = ConfigManager()