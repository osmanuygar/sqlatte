
from typing import Dict, Any, Literal, Optional
from src.core.llm_provider import LLMProvider
from src.core.db_provider import DatabaseProvider
 
# Import ops agent base class
from src.providers.ops_agents.base_ops_agent import BaseOpsAgent
 
# Task type
LLMTask = Literal["intent_detection", "chat", "sql", "insights", "ops_insights"]
 
# Global ops agent instance
_ops_agent: Optional[BaseOpsAgent] = None
 
 
class ProviderFactory:
    """Factory for instantiating providers based on configuration"""
 
    LLM_PROVIDERS = {
        'anthropic': 'src.providers.llm.anthropic_provider.AnthropicProvider',
        'gemini':    'src.providers.llm.gemini_provider.GeminiProvider',
        'vertexai':  'src.providers.llm.vertexai_provider.VertexAIProvider',
    }
 
    DB_PROVIDERS = {
        'trino':      'src.providers.database.trino_provider.TrinoProvider',
        'postgresql': 'src.providers.database.postgresql_provider.PostgreSQLProvider',
        'mysql':      'src.providers.database.mysql_provider.MySQLProvider',
        'bigquery':   'src.providers.database.bigquery_provider.BigQueryProvider',
    }
 
    @staticmethod
    def create_llm_provider(config: Dict[str, Any]) -> LLMProvider:
        """
        Create default LLM provider
        Backward compatibility maintained
        """
        provider_name = config['llm']['provider']
 
        if provider_name not in ProviderFactory.LLM_PROVIDERS:
            raise ValueError(f"Unknown LLM provider: {provider_name}")
 
        class_path = ProviderFactory.LLM_PROVIDERS[provider_name]
        module_path, class_name = class_path.rsplit('.', 1)
        module = __import__(module_path, fromlist=[class_name])
        provider_class = getattr(module, class_name)
        provider_config = config['llm'][provider_name]
 
        return provider_class(provider_config)
 
    @staticmethod
    def create_llm_provider_for_task(
        config: Dict[str, Any],
        task: LLMTask
    ) -> LLMProvider:
        """
        Create LLM provider with task-specific model routing
        
        Uses model_routing from config.yaml if defined,
        falls back to default model otherwise
        """
        provider_name = config['llm']['provider']
 
        if provider_name not in ProviderFactory.LLM_PROVIDERS:
            raise ValueError(f"Unknown LLM provider: {provider_name}")
 
        # Deep copy provider config to avoid mutation
        import copy
        provider_config = copy.deepcopy(config['llm'][provider_name])
 
        # Check for model_routing
        model_routing = provider_config.pop('model_routing', {})
        task_model = model_routing.get(task)
 
        if task_model:
            original_model = provider_config.get('model', 'unknown')
            provider_config['model'] = task_model
            print(f"🎯 [ModelRouting] task={task} → model={task_model} (default={original_model})")
        else:
            print(f"🎯 [ModelRouting] task={task} → model={provider_config.get('model')} (default, no routing)")
 
        # Load and instantiate provider class
        class_path = ProviderFactory.LLM_PROVIDERS[provider_name]
        module_path, class_name = class_path.rsplit('.', 1)
        module = __import__(module_path, fromlist=[class_name])
        provider_class = getattr(module, class_name)
 
        return provider_class(provider_config)
 
    @staticmethod
    def create_db_provider(config: Dict[str, Any]) -> DatabaseProvider:
        """Create database provider - unchanged"""
        provider_name = config['database']['provider']
 
        if provider_name not in ProviderFactory.DB_PROVIDERS:
            raise ValueError(f"Unknown database provider: {provider_name}")
 
        class_path = ProviderFactory.DB_PROVIDERS[provider_name]
        module_path, class_name = class_path.rsplit('.', 1)
        module = __import__(module_path, fromlist=[class_name])
        provider_class = getattr(module, class_name)
        provider_config = config['database'][provider_name]
 
        return provider_class(provider_config)
 
    # ═══════════════════════════════════════════════════════════
    # NEW: OPS AGENT SUPPORT
    # ═══════════════════════════════════════════════════════════
 
    @staticmethod
    def create_ops_agent(config: Dict[str, Any]) -> Optional[BaseOpsAgent]:
        """
        Create operational agent from config
        
        config.yaml example:
          ops_agent:
            enabled: true
            provider: bigquery_ops
            config:
              project_id: analytics-prod
              region: US
              credentials_path: /path/to/creds.json
              allowed_operations:  # Optional
                - get_expensive_queries
                - forecast_monthly_costs
        
        Args:
            config: Full configuration dictionary
            
        Returns:
            BaseOpsAgent instance or None if disabled
            
        Raises:
            ValueError: If provider unknown or config invalid
        """
        ops_config = config.get('ops_agent', {})
        
        # Check if enabled
        if not ops_config.get('enabled', False):
            print("⏭️  Ops Agent disabled in config")
            return None
        
        provider = ops_config.get('provider')
        
        if not provider:
            raise ValueError("ops_agent.provider not specified in config.yaml")
        
        # Create appropriate ops agent
        if provider == 'bigquery_ops':
            from src.providers.ops_agents.bigquery_ops_agent import BigQueryOpsAgent
            
            agent_config = ops_config.get('config', {})
            
            print(f"🔧 Initializing BigQuery Ops Agent...")
            print(f"   Project: {agent_config.get('project_id')}")
            print(f"   Region: {agent_config.get('region')}")
            
            agent = BigQueryOpsAgent(agent_config)
            
            # Health check (async but we run it sync for initialization)
            import asyncio
            try:
                health = asyncio.run(agent.health_check())
                
                if not health.get('healthy'):
                    print(f"⚠️  Ops Agent unhealthy: {health.get('error', health.get('message'))}")
                else:
                    info = agent.get_connection_info()
                    print(f"✅ Ops Agent ready: {info['operations_count']} operations available")
            except Exception as e:
                print(f"⚠️  Ops Agent health check failed: {e}")
            
            return agent
        
        else:
            raise ValueError(f"Unknown ops agent provider: {provider}")
 
 
# ═══════════════════════════════════════════════════════════
# GLOBAL OPS AGENT MANAGEMENT
# ═══════════════════════════════════════════════════════════
 
def initialize_ops_agent(config: Dict[str, Any]) -> None:
    """
    Initialize global ops agent instance
    
    Called during app startup
    
    Args:
        config: Full configuration dictionary
    """
    global _ops_agent
    
    try:
        _ops_agent = ProviderFactory.create_ops_agent(config)
    except Exception as e:
        print(f"❌ Failed to initialize ops agent: {e}")
        import traceback
        traceback.print_exc()
        _ops_agent = None
 
 
def get_ops_agent() -> Optional[BaseOpsAgent]:
    """
    Get global ops agent instance
    
    Returns:
        BaseOpsAgent instance or None if not configured
    """
    return _ops_agent
 
 
# ═══════════════════════════════════════════════════════════
# PROVIDER RELOAD (UPDATED)
# ═══════════════════════════════════════════════════════════
 
def reload_providers(config_manager):
    """
    Reload LLM, Database, and Ops Agent providers
    
    UPDATED to include ops agent reload
    """
    # Import here to avoid circular dependency
    from src.api.app import llm_provider, db_provider
    
    global _ops_agent
    
    print("\n🔄 Reloading providers...")
    current_config = config_manager.get_config()
    
    try:
        # Recreate LLM provider
        new_llm = ProviderFactory.create_llm_provider(current_config)
        # Note: This updates global in app.py, not here
        print(f"✅ LLM provider reloaded: {new_llm.get_model_name()}")
    except Exception as e:
        print(f"⚠️ Failed to reload LLM provider: {e}")
        raise
    
    try:
        # Recreate Database provider
        new_db = ProviderFactory.create_db_provider(current_config)
        print(f"✅ Database provider reloaded: {new_db.get_connection_info()['type']}")
    except Exception as e:
        print(f"⚠️ Failed to reload Database provider: {e}")
        raise
    
    try:
        # Recreate Ops Agent (NEW)
        new_ops = ProviderFactory.create_ops_agent(current_config)
        _ops_agent = new_ops
        if _ops_agent:
            info = _ops_agent.get_connection_info()
            print(f"✅ Ops Agent reloaded: {info['operations_count']} operations")
        else:
            print("⏭️  Ops Agent disabled")
    except Exception as e:
        print(f"⚠️ Failed to reload Ops Agent: {e}")
        import traceback
        traceback.print_exc()
        # Don't raise - ops agent is optional
    
    print("🎉 Provider reload complete!\n")
    
    return {
        "llm": {
            "provider": current_config['llm']['provider'],
            "model": new_llm.get_model_name()
        },
        "database": {
            "provider": current_config['database']['provider'],
            "info": new_db.get_connection_info()
        },
        "ops_agent": {
            "enabled": _ops_agent is not None,
            "info": _ops_agent.get_connection_info() if _ops_agent else None
        }
    }