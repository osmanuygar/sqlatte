"""
SQLatte Config Manager - Runtime Configuration Management
Allows config updates without restart
"""

import os
import yaml
import threading
from typing import Dict, Any, Optional
from copy import deepcopy


class ConfigManager:
    """
    Singleton Config Manager
    - Loads config from YAML on startup
    - Allows runtime updates via API
    - Thread-safe config updates
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
            self.initialized = True

    def load_from_file(self, config_path: str) -> Dict[str, Any]:
        """Load initial config from YAML file"""
        self.config_path = config_path

        with open(config_path, 'r') as f:
            file_config = yaml.safe_load(f)

        # Resolve environment variables
        from src.core.config_loader import ConfigLoader
        resolved_config = ConfigLoader._resolve_env_vars(file_config)

        with self._config_lock:
            self.config = resolved_config

        print(f"✅ Config loaded from: {config_path}")
        return self.get_config()

    def get_config(self) -> Dict[str, Any]:
        """Get current active configuration"""
        with self._config_lock:
            # Merge file config with runtime overrides
            merged = deepcopy(self.config)
            self._deep_merge(merged, self.runtime_overrides)
            return merged

    def get_safe_config(self) -> Dict[str, Any]:
        """Get config with sensitive data masked"""
        config = self.get_config()
        safe_config = deepcopy(config)

        # Mask sensitive fields
        sensitive_fields = ['api_key', 'password', 'credentials_json', 'credentials_path']

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
        persist: bool = False
    ) -> Dict[str, Any]:
        """
        Update configuration at runtime

        Args:
            updates: Configuration updates (nested dict)
            persist: If True, save to config.yaml file

        Returns:
            Updated configuration
        """
        with self._config_lock:
            # Apply updates to runtime overrides
            self._deep_merge(self.runtime_overrides, updates)

            # If persist, write to file
            if persist and self.config_path:
                self._save_to_file()

            return self.get_config()

    def update_llm_config(
        self,
        provider: str,
        provider_config: Dict[str, Any]
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
        return self.update_config(updates)

    def update_database_config(
        self,
        provider: str,
        provider_config: Dict[str, Any]
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

        updates = {
            'database': {
                'provider': provider,
                provider: provider_config
            }
        }
        return self.update_config(updates)

    def reset_to_file(self):
        """Reset runtime overrides, reload from file"""
        with self._config_lock:
            self.runtime_overrides = {}

            if self.config_path:
                self.load_from_file(self.config_path)

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
        """Mask sensitive values for display"""
        if not value or len(value) < 8:
            return '***'

        # Show first 3 and last 3 characters
        return f"{value[:3]}...{value[-3:]}"

    def _save_to_file(self):
        """Save current config to YAML file"""
        if not self.config_path:
            return

        merged_config = self.get_config()

        with open(self.config_path, 'w') as f:
            yaml.dump(merged_config, f, default_flow_style=False, indent=2)

        print(f"💾 Config saved to: {self.config_path}")

    def test_connection(
        self,
        provider_type: str,
        provider: str,
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Test a provider configuration before applying
        WITH ENHANCED DEBUG LOGGING

        Args:
            provider_type: 'llm' or 'database'
            provider: Provider name (e.g., 'anthropic', 'trino')
            config: Provider configuration

        Returns:
            Test result with status and message
        """
        # 🔍 DEBUG: Log what we received
        print(f"\n{'='*60}")
        print(f"🧪 [TEST CONNECTION] Starting...")
        print(f"   Type: {provider_type}")
        print(f"   Provider: {provider}")
        print(f"   Config received from browser:")
        for key, value in config.items():
            if 'password' in key.lower() or 'api_key' in key.lower():
                print(f"      {key}: {'*' * len(str(value)) if value else '(empty)'}")
            else:
                print(f"      {key}: {value}")
        print(f"{'='*60}\n")

        try:
            if provider_type == 'llm':
                return self._test_llm(provider, config)
            elif provider_type == 'database':
                return self._test_database(provider, config)
            else:
                return {
                    'success': False,
                    'message': f'Unknown provider type: {provider_type}'
                }
        except Exception as e:
            print(f"❌ [TEST CONNECTION] Exception: {e}")
            return {
                'success': False,
                'message': f'Test failed: {str(e)}'
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