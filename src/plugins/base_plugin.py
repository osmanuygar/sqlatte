"""
SQLatte Plugin System - Base Plugin Class
Allows extending SQLatte functionality without modifying core
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from fastapi import FastAPI, Request


class BasePlugin(ABC):
    """
    Base class for SQLatte plugins

    Plugins can:
    - Add custom routes
    - Modify request/response flow
    - Extend authentication
    - Add custom database providers
    - Inject middleware
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize plugin with configuration

        Args:
            config: Plugin-specific configuration from config.yaml
        """
        self.config = config
        self.enabled = config.get('enabled', False)
        self.name = self.__class__.__name__
        self.initialized = False

    def is_enabled(self) -> bool:
        """Check if plugin is enabled"""
        return self.enabled

    @abstractmethod
    def initialize(self, app: FastAPI) -> None:
        """
        Initialize plugin (called on startup)

        Args:
            app: FastAPI application instance
        """
        pass

    def register_routes(self, app: FastAPI) -> None:
        """
        Register custom routes

        Args:
            app: FastAPI application instance
        """
        pass

    async def before_request(self, request: Request) -> Optional[Any]:
        """
        Hook called before each request

        Args:
            request: FastAPI request

        Returns:
            None to continue, or Response to short-circuit
        """
        return None

    async def after_request(self, request: Request, response: Any) -> Any:
        """
        Hook called after each request

        Args:
            request: FastAPI request
            response: Response object

        Returns:
            Modified response or original
        """
        return response

    def shutdown(self) -> None:
        """Cleanup on shutdown"""
        pass

    def get_info(self) -> Dict[str, Any]:
        """Get plugin information"""
        return {
            "name": self.name,
            "enabled": self.enabled,
            "initialized": self.initialized,
            "config": self._safe_config()
        }

    def _safe_config(self) -> Dict[str, Any]:
        """Return config with sensitive data masked"""
        safe = {}
        for key, value in self.config.items():
            if any(sensitive in key.lower() for sensitive in ['password', 'secret', 'key', 'token']):
                safe[key] = '***masked***'
            else:
                safe[key] = value
        return safe


class PluginManager:
    """
    Manages plugin lifecycle
    """

    def __init__(self):
        self.plugins: Dict[str, BasePlugin] = {}
        self.initialized = False

    def register_plugin(self, plugin: BasePlugin) -> None:
        """Register a plugin"""
        if not plugin.is_enabled():
            print(f"⏸️  Plugin '{plugin.name}' is disabled, skipping")
            return

        self.plugins[plugin.name] = plugin
        print(f"✅ Plugin registered: {plugin.name}")

    def initialize_all(self, app: FastAPI) -> None:
        """Initialize all registered plugins"""
        print(f"\n🔌 Initializing {len(self.plugins)} plugins...")

        for name, plugin in self.plugins.items():
            try:
                plugin.initialize(app)
                plugin.register_routes(app)
                plugin.initialized = True
                print(f"   ✅ {name} initialized")
            except Exception as e:
                print(f"   ❌ {name} failed: {e}")
                import traceback
                traceback.print_exc()

        self.initialized = True
        print(f"🎉 Plugin initialization complete\n")

    def get_plugin(self, name: str) -> Optional[BasePlugin]:
        """Get plugin by name"""
        return self.plugins.get(name)

    def list_plugins(self) -> Dict[str, Dict[str, Any]]:
        """List all plugins with their info"""
        return {
            name: plugin.get_info()
            for name, plugin in self.plugins.items()
        }

    async def before_request(self, request: Request) -> Optional[Any]:
        """Call before_request hook on all plugins"""
        for plugin in self.plugins.values():
            result = await plugin.before_request(request)
            if result is not None:
                return result
        return None

    async def after_request(self, request: Request, response: Any) -> Any:
        """Call after_request hook on all plugins"""
        for plugin in self.plugins.values():
            response = await plugin.after_request(request, response)
        return response

    def shutdown_all(self) -> None:
        """Shutdown all plugins"""
        print("\n🔌 Shutting down plugins...")
        for name, plugin in self.plugins.items():
            try:
                plugin.shutdown()
                print(f"   ✅ {name} shutdown")
            except Exception as e:
                print(f"   ⚠️ {name} shutdown error: {e}")


# Global plugin manager instance
plugin_manager = PluginManager()