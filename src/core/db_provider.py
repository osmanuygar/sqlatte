"""
Abstract base class for database providers.
Supports: Trino, Presto, ClickHouse, PostgreSQL, MySQL, etc.
"""

from abc import ABC, abstractmethod
from typing import List, Tuple, Any, Dict


class DatabaseProvider(ABC):
    """Abstract base class for database providers"""
    
    def __init__(self, config: dict):
        """
        Initialize database provider with configuration
        
        Args:
            config: Provider-specific configuration
        """
        self.config = config
    
    @abstractmethod
    def connect(self):
        """Establish connection to database"""
        pass
    
    @abstractmethod
    def get_tables(self) -> List[str]:
        """
        Get list of available tables
        
        Returns:
            List of table names
        """
        pass
    
    @abstractmethod
    def get_table_schema(self, table_name: str) -> str:
        """
        Get schema information for a table
        
        Args:
            table_name: Name of the table
            
        Returns:
            Schema information as string
        """
        pass
    
    @abstractmethod
    def execute_query(self, sql: str) -> Tuple[List[str], List[List[Any]]]:
        """
        Execute SQL query
        
        Args:
            sql: SQL query to execute
            
        Returns:
            Tuple of (column_names, rows)
        """
        pass

    def discover_tables(self, search_term: str) -> Dict[str, Any]:
        """
        Cross-catalog table/collection name search — metadata only, no row
        data. Default: unsupported. Only TrinoProvider overrides this
        (system.jdbc.tables gives a real federated view across every
        catalog Trino knows about; other providers have no equivalent).

        Returns: {"matches": [{"catalog", "schema", "table"}, ...],
                  "columns": {"cat.schema.table": [col, ...], ...}}
        """
        raise NotImplementedError(
            f"Table discovery isn't supported for the '{self.__class__.__name__}' provider (Trino only)."
        )

    @abstractmethod
    def health_check(self) -> bool:
        """Check if database connection is healthy"""
        pass
    
    @abstractmethod
    def get_connection_info(self) -> dict:
        """Get connection information (for display purposes)"""
        pass
