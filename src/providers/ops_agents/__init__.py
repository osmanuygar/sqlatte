"""
SQLatte Ops Agent System

Provides operational automation for database platforms through
predefined playbooks and diagnostic tools.
"""

from .base_ops_agent import (
    BaseOpsAgent,
    OperationCategory,
    OperationResult
)

__all__ = [
    'BaseOpsAgent',
    'OperationCategory',
    'OperationResult'
]
