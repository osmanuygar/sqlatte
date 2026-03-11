"""
Factory for creating LLM and Database providers
─────────────────────────────────────────────────
Orijinal dosyaya create_llm_provider_for_task() metodunu ekle.
Mevcut create_llm_provider() ve create_db_provider() dokunma.
"""

from typing import Dict, Any, Literal
from src.core.llm_provider import LLMProvider
from src.core.db_provider import DatabaseProvider

# Task type
LLMTask = Literal["intent_detection", "chat", "sql", "insights"]


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
        Mevcut metod — default provider oluşturur.
        Geriye dönük uyumluluk korunuyor.
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
        Task'a özel model ile LLM provider oluşturur.

        config.yaml'da `model_routing` tanımlıysa task'a ait modeli kullanır,
        yoksa default model ile fallback yapar.

        Args:
            config: Tam config dict (config_manager.get_config())
            task:   "intent_detection" | "chat" | "sql" | "insights"

        Returns:
            LLMProvider — task'a uygun model ile initialize edilmiş

        Örnek config.yaml:
            llm:
              provider: anthropic
              anthropic:
                model: claude-sonnet-4-20250514
                model_routing:
                  intent_detection: claude-haiku-4-5-20251001
                  sql: claude-opus-4-6
        """
        provider_name = config['llm']['provider']

        if provider_name not in ProviderFactory.LLM_PROVIDERS:
            raise ValueError(f"Unknown LLM provider: {provider_name}")

        # Provider config'in kopyasını al (orijinali değiştirme)
        import copy
        provider_config = copy.deepcopy(config['llm'][provider_name])

        # model_routing varsa task'a ait modeli bul
        model_routing = provider_config.pop('model_routing', {})
        task_model = model_routing.get(task)

        if task_model:
            original_model = provider_config.get('model', 'unknown')
            provider_config['model'] = task_model
            print(f"🎯 [ModelRouting] task={task} → model={task_model} (default={original_model})")
        else:
            print(f"🎯 [ModelRouting] task={task} → model={provider_config.get('model')} (default, no routing)")

        # Provider class'ı yükle ve oluştur
        class_path = ProviderFactory.LLM_PROVIDERS[provider_name]
        module_path, class_name = class_path.rsplit('.', 1)
        module = __import__(module_path, fromlist=[class_name])
        provider_class = getattr(module, class_name)

        return provider_class(provider_config)

    @staticmethod
    def create_db_provider(config: Dict[str, Any]) -> DatabaseProvider:
        """Database provider oluşturur — değişiklik yok."""
        provider_name = config['database']['provider']

        if provider_name not in ProviderFactory.DB_PROVIDERS:
            raise ValueError(f"Unknown database provider: {provider_name}")

        class_path = ProviderFactory.DB_PROVIDERS[provider_name]
        module_path, class_name = class_path.rsplit('.', 1)
        module = __import__(module_path, fromlist=[class_name])
        provider_class = getattr(module, class_name)
        provider_config = config['database'][provider_name]

        return provider_class(provider_config)