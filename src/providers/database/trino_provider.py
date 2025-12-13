"""
Trino Database Provider
"""

import trino
from trino.auth import BasicAuthentication
from typing import List, Tuple, Any
from src.core.db_provider import DatabaseProvider


class TrinoProvider(DatabaseProvider):
    """Trino database provider implementation"""
    
    def __init__(self, config: dict):
        super().__init__(config)
        self.host = config.get('host', 'localhost')
        self.port = config.get('port', 8080)
        self.user = config.get('user', 'admin')
        self.password = config.get('password', '')
        self.catalog = config.get('catalog', 'hive')
        self.schema = config.get('schema', 'default')
        self.http_scheme = config.get('http_scheme', 'https')
        
        self.connection = None
    
    def connect(self):
        """Establish Trino connection"""
        auth = BasicAuthentication(
            username=self.user,
            password=self.password
        )
        
        self.connection = trino.dbapi.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            auth=auth,
            catalog=self.catalog,
            schema=self.schema,
            http_scheme=self.http_scheme,
        )
        return self.connection
    
    def get_tables(self) -> List[str]:
        """Get list of tables"""
        conn = self.connect()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SHOW TABLES")
            tables = [row[0] for row in cursor.fetchall()]
            return tables
        finally:
            cursor.close()
            conn.close()
    
    def get_table_schema(self, table_name: str) -> str:
        """Get table schema"""
        conn = self.connect()
        cursor = conn.cursor()
        
        try:
            cursor.execute(f"DESCRIBE {table_name}")
            columns = cursor.fetchall()
            
            schema_info = f"Table: {table_name}\nColumns:\n"
            for col in columns:
                schema_info += f"  - {col[0]} ({col[1]})\n"
            
            return schema_info
        except Exception as e:
            return f"Could not fetch schema for {table_name}: {str(e)}"
        finally:
            cursor.close()
            conn.close()
    
    def execute_query(self, sql: str) -> Tuple[List[str], List[List[Any]]]:
        """Execute SQL query"""
        conn = self.connect()
        cursor = conn.cursor()
        
        try:
            cursor.execute(sql)
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            data = [list(row) for row in rows]
            return columns, data
        finally:
            cursor.close()
            conn.close()
    
    def health_check(self) -> bool:
        """Check Trino connection"""
        try:
            conn = self.connect()
            conn.close()
            return True
        except Exception:
            return False
    
    def get_connection_info(self) -> dict:
        """Get connection info"""
        return {
            "type": "trino",
            "host": self.host,
            "port": self.port,
            "catalog": self.catalog,
            "schema": self.schema,
            "user": self.user
        }
