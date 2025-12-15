"""
Factory for creating LLM and Database providers
"""

from typing import Dict, Any
from src.core.llm_provider import LLMProvider
from src.core.db_provider import DatabaseProvider


class ProviderFactory:
    """Factory for instantiating providers based on configuration"""
    
    # Registry of available providers
    LLM_PROVIDERS = {
        'anthropic': 'src.providers.llm.anthropic_provider.AnthropicProvider',
        'gemini': 'src.providers.llm.gemini_provider.GeminiProvider',
        'vertexai': 'src.providers.llm.vertexai_provider.VertexAIProvider',
        # 'openai': 'src.providers.llm.openai_provider.OpenAIProvider',
        # 'azure_openai': 'src.providers.llm.azure_provider.AzureOpenAIProvider',
        # 'ollama': 'src.providers.llm.ollama_provider.OllamaProvider',
    }

    DB_PROVIDERS = {
        'trino': 'src.providers.database.trino_provider.TrinoProvider',
        # 'presto': 'src.providers.database.presto_provider.PrestoProvider',
        # 'clickhouse': 'src.providers.database.clickhouse_provider.ClickHouseProvider',
        # 'postgresql': 'src.providers.database.postgresql_provider.PostgreSQLProvider',
    }

    @staticmethod
    def create_llm_provider(config: Dict[str, Any]) -> LLMProvider:
        """
        Create LLM provider based on configuration

        Args:
            config: Configuration dictionary

        Returns:
            LLMProvider instance
        """
        provider_name = config['llm']['provider']

        if provider_name not in ProviderFactory.LLM_PROVIDERS:
            raise ValueError(f"Unknown LLM provider: {provider_name}")

        # Get provider class
        class_path = ProviderFactory.LLM_PROVIDERS[provider_name]
        module_path, class_name = class_path.rsplit('.', 1)

        # Dynamic import
        module = __import__(module_path, fromlist=[class_name])
        provider_class = getattr(module, class_name)

        # Get provider-specific config
        provider_config = config['llm'][provider_name]

        return provider_class(provider_config)

    @staticmethod
    def create_db_provider(config: Dict[str, Any]) -> DatabaseProvider:
        """
        Create database provider based on configuration

        Args:
            config: Configuration dictionary

        Returns:
            DatabaseProvider instance
        """
        provider_name = config['database']['provider']

        if provider_name not in ProviderFactory.DB_PROVIDERS:
            raise ValueError(f"Unknown database provider: {provider_name}")

        # Get provider class
        class_path = ProviderFactory.DB_PROVIDERS[provider_name]
        module_path, class_name = class_path.rsplit('.', 1)

        # Dynamic import
        module = __import__(module_path, fromlist=[class_name])
        provider_class = getattr(module, class_name)

        # Get provider-specific config
        provider_config = config['database'][provider_name]

        return provider_class(provider_config)