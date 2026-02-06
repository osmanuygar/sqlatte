"""
Abstract base class for LLM providers.
Supports: Anthropic, OpenAI, Azure OpenAI, Ollama, etc.
"""

from abc import ABC, abstractmethod
from typing import Tuple, Dict


class LLMProvider(ABC):
    """Abstract base class for LLM providers"""
    
    def __init__(self, config: dict):
        """
        Initialize LLM provider with configuration
        
        Args:
            config: Provider-specific configuration
        """
        self.config = config
    
    @abstractmethod
    def determine_intent(self, question: str, schema_info: str) -> Dict[str, any]:
        """
        Determine if question requires SQL or is general chat
        
        Args:
            question: User's question
            schema_info: Available database schema
            
        Returns:
            {
                "intent": "sql" or "chat",
                "confidence": 0.0-1.0,
                "reasoning": "explanation"
            }
        """
        pass
    
    @abstractmethod
    def generate_chat_response(self, question: str, context: str = "") -> str:
        """
        Generate conversational response (non-SQL)
        
        Args:
            question: User's question
            context: Optional context
            
        Returns:
            Chat response text
        """
        pass
    
    @abstractmethod
    def generate_sql(self, question: str, schema_info: str) -> Tuple[str, str]:
        """
        Generate SQL query from natural language question
        
        Args:
            question: Natural language question
            schema_info: Database schema information
            
        Returns:
            Tuple of (sql_query, explanation)
        """
        pass
    
    @abstractmethod
    def get_model_name(self) -> str:
        """Get the model name being used"""
        pass
    
    @abstractmethod
    def health_check(self) -> bool:
        """Check if the LLM provider is accessible"""
        pass

    # ============================================
    # Prompt Management
    # ============================================
    def get_prompt(self, prompt_type: str, default: str = "") -> str:
        """
        Get prompt from config with fallback to default

        Args:
            prompt_type: Type of prompt (intent_detection, barista_personality, sql_generation, insights_generation)
            default: Default prompt if not found in config

        Returns:
            Prompt text
        """
        try:
            # Try to get from config
            from src.core.config_manager_enhanced import config_manager
            config = config_manager.get_config()

            prompts = config.get('prompts', {})
            prompt = prompts.get(prompt_type, default)

            # If empty, use default
            if not prompt or prompt.strip() == '':
                return default

            return prompt

        except Exception as e:
            print(f"⚠️ Could not load prompt '{prompt_type}' from config: {e}")
            return default