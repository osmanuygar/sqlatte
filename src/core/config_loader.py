"""
Configuration loader and environment variable resolver
"""

import os
import yaml
import re
from typing import Any, Dict


class ConfigLoader:
    """Load and parse configuration with environment variable substitution"""
    
    @staticmethod
    def load(config_path: str) -> Dict[str, Any]:
        """
        Load configuration from YAML file
        
        Args:
            config_path: Path to config.yaml file
            
        Returns:
            Parsed configuration dictionary
        """
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        # Resolve environment variables
        return ConfigLoader._resolve_env_vars(config)
    
    @staticmethod
    def _resolve_env_vars(config: Any) -> Any:
        """
        Recursively resolve ${VAR} and ${VAR:default} patterns
        
        Supports:
        - ${VAR} - Required variable, raises error if not set
        - ${VAR:default} - Optional variable with default value
        """
        if isinstance(config, dict):
            return {k: ConfigLoader._resolve_env_vars(v) for k, v in config.items()}
        elif isinstance(config, list):
            return [ConfigLoader._resolve_env_vars(item) for item in config]
        elif isinstance(config, str):
            return ConfigLoader._resolve_string(config)
        else:
            return config
    
    @staticmethod
    def _resolve_string(value: str) -> Any:
        """Resolve environment variables in string"""
        # Pattern: ${VAR} or ${VAR:default}
        pattern = r'\$\{([^}:]+)(?::([^}]*))?\}'
        
        def replacer(match):
            var_name = match.group(1)
            default_value = match.group(2)
            
            env_value = os.getenv(var_name)
            
            if env_value is not None:
                return env_value
            elif default_value is not None:
                return default_value
            else:
                raise ValueError(f"Environment variable '{var_name}' is required but not set")
        
        resolved = re.sub(pattern, replacer, value)
        
        # Try to convert to int if possible
        if resolved.isdigit():
            return int(resolved)
        
        # Try to convert to bool
        if resolved.lower() in ('true', 'false'):
            return resolved.lower() == 'true'
        
        return resolved
