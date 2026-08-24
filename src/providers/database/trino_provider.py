"""
Trino Database Provider
"""

import trino
from trino.auth import BasicAuthentication
from typing import List, Tuple, Any, Dict
from src.core.db_provider import DatabaseProvider


class TrinoProvider(DatabaseProvider):
    """Trino database provider implementation"""
    
    def __init__(self, config: dict):
        super().__init__(config)
        self.host = config.get('host', 'localhost')
        self.port = config.get('port', 8080)
        self.user = config.get('user', 'admin')
        self.password = config.get('password', '')
        # No hardcoded catalog/schema fallback: leaving these unset (None) lets
        # trino.dbapi.connect() open a catalog-less session, which callers like
        # the discovery-token flow (intentionally cross-catalog, see
        # auth_plugin.py's /auth/discovery-token) rely on. A config-supplied
        # catalog/schema still take priority as before.
        self.catalog = config.get('catalog') or None
        self.schema = config.get('schema') or None
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
        from src.core.sql_validator import validate_identifier
        conn = self.connect()
        cursor = conn.cursor()

        try:
            cursor.execute(f"DESCRIBE {validate_identifier(table_name)}")
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
    
    # How many of the top matches get an automatic DESCRIBE for column info.
    # Was 5; a catalog-less list_tables now routes through this with an
    # empty search_term (see the docstring below), so a wider slice is more
    # useful for actually browsing rather than just locating one table.
    DEFAULT_DESCRIBE_LIMIT = 25

    def discover_tables(
        self,
        search_term: str,
        catalog_schema_map: Dict[str, list] | None = None,
        describe_limit: int = DEFAULT_DESCRIBE_LIMIT,
    ) -> Dict[str, Any]:
        """
        Cross-catalog table/collection name search via system.jdbc.tables —
        Trino's federated JDBC metadata catalog, spans every catalog this
        connection's user can see in one query. Metadata only, no row data.

        search_term: partial table/collection name match. Empty string means
        "list everything" — used to back list_tables for catalog-less
        (discovery-shaped) sessions instead of a separate per-catalog
        SHOW TABLES loop.

        catalog_schema_map: optional {catalog: [allowed_schema, ...]}
        allowlist (plugins.auth.allowed_catalogs). When given, results are
        restricted to it server-side — narrower than "every catalog this
        Trino user can see" — which both keeps the result set relevant (less
        noise for the LLM to sift through) and keeps a catalog-less token
        from ever seeing metadata for catalogs it isn't allowed to query
        anyway. An empty/omitted map means unrestricted, same as before.

        Auto-DESCRIBEs the top `describe_limit` matches for column info
        (best-effort, one shared connection for all of them — a DESCRIBE
        failure, e.g. a permissions gap on one specific catalog, just drops
        that table from `columns`, doesn't fail the whole call).
        """
        from src.core.sql_validator import validate_identifier

        conn = self.connect()
        cursor = conn.cursor()
        try:
            like_pattern = f"%{search_term.lower()}%" if search_term else "%"
            sql = (
                "SELECT table_cat, table_schem, table_name FROM system.jdbc.tables "
                "WHERE LOWER(table_name) LIKE ?"
            )
            params: list = [like_pattern]
            if catalog_schema_map:
                placeholders = ", ".join("?" for _ in catalog_schema_map)
                sql += f" AND table_cat IN ({placeholders})"
                params.extend(catalog_schema_map.keys())
            sql += " ORDER BY table_cat, table_schem, table_name LIMIT 500"
            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall()
        finally:
            cursor.close()
            conn.close()

        # table_cat IN (...) already narrowed to allowed catalogs; schema is
        # per-catalog (some catalogs restrict to specific schemas, others
        # allow any), so that half of the allowlist is applied in Python.
        if catalog_schema_map:
            allowed = {c.lower(): [s.lower() for s in schemas] for c, schemas in catalog_schema_map.items()}
            rows = [
                row for row in rows
                if not allowed.get((row[0] or "").lower()) or (row[1] or "").lower() in allowed[(row[0] or "").lower()]
            ]

        matches = [{"catalog": row[0], "schema": row[1], "table": row[2]} for row in rows]

        columns: Dict[str, List[str]] = {}
        to_describe = matches[:describe_limit]
        if to_describe:
            # One shared connection for the whole batch — was reopening a
            # fresh connection per table, which only mattered when this
            # capped at 5; now that it's a wider slice, that would mean
            # describe_limit sequential connects.
            desc_conn = self.connect()
            desc_cursor = desc_conn.cursor()
            try:
                for m in to_describe:
                    try:
                        ref = f"{validate_identifier(m['catalog'])}.{validate_identifier(m['schema'])}.{validate_identifier(m['table'])}"
                    except ValueError:
                        continue
                    try:
                        desc_cursor.execute(f"DESCRIBE {ref}")
                        columns[ref] = [row[0] for row in desc_cursor.fetchall()]
                    except Exception:
                        pass
            finally:
                desc_cursor.close()
                desc_conn.close()

        return {"matches": matches, "columns": columns}

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
