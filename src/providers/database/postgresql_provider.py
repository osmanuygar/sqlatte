"""
PostgreSQL Database Provider - Super Robust Version
Handles all edge cases including tuple index errors
"""

import psycopg2
from psycopg2.extras import RealDictCursor
from typing import List, Tuple, Any
from src.core.db_provider import DatabaseProvider


class PostgreSQLProvider(DatabaseProvider):
    """PostgreSQL database provider - Super robust implementation"""

    def __init__(self, config: dict):
        super().__init__(config)
        self.host = config.get('host', 'localhost')
        self.port = config.get('port', 5432)
        self.database = config.get('database', 'postgres')
        self.user = config.get('user', 'postgres')
        self.password = config.get('password', '')
        self.schema = config.get('schema', 'public')

        # Connection pool settings
        self.min_connections = config.get('min_connections', 1)
        self.max_connections = config.get('max_connections', 10)

        self.connection = None

    def connect(self):
        """Establish PostgreSQL connection"""
        try:
            self.connection = psycopg2.connect(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password,
                options=f'-c search_path={self.schema}',
                connect_timeout=10
            )
            return self.connection
        except Exception as e:
            raise Exception(f"PostgreSQL connection failed: {str(e)}")

    def get_tables(self) -> List[str]:
        """Get list of tables in the schema"""
        conn = self.connect()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = %s 
                AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """, (self.schema,))

            tables = [row[0] for row in cursor.fetchall()]
            return tables
        except Exception as e:
            raise Exception(f"Failed to get tables: {str(e)}")
        finally:
            cursor.close()
            conn.close()

    def get_table_schema(self, table_name: str) -> str:
        """Get table schema with comprehensive error handling"""
        conn = None
        cursor = None

        try:
            conn = self.connect()
            cursor = conn.cursor()

            # Verify table exists first
            cursor.execute("""
                SELECT COUNT(*) 
                FROM information_schema.tables 
                WHERE table_schema = %s 
                AND table_name = %s
            """, (self.schema, table_name))

            result = cursor.fetchone()
            if not result or result[0] == 0:
                return f"❌ Table '{table_name}' not found in schema '{self.schema}'"

            # Build schema info
            schema_info = f"Table: {self.schema}.{table_name}\n"
            schema_info += "=" * 60 + "\n\n"

            # ==========================================
            # GET COLUMNS - Safe version
            # ==========================================
            try:
                cursor.execute("""
                    SELECT 
                        column_name,
                        data_type,
                        character_maximum_length,
                        numeric_precision,
                        numeric_scale,
                        is_nullable,
                        column_default
                    FROM information_schema.columns
                    WHERE table_schema = %s 
                    AND table_name = %s
                    ORDER BY ordinal_position
                """, (self.schema, table_name))

                columns = cursor.fetchall()

                if columns:
                    schema_info += "COLUMNS:\n"
                    schema_info += "-" * 60 + "\n"

                    for col in columns:
                        try:
                            col_name = col[0] if len(col) > 0 else 'unknown'
                            data_type = col[1] if len(col) > 1 else 'unknown'
                            max_length = col[2] if len(col) > 2 else None
                            num_precision = col[3] if len(col) > 3 else None
                            num_scale = col[4] if len(col) > 4 else None
                            nullable = col[5] if len(col) > 5 else 'YES'
                            default = col[6] if len(col) > 6 else None

                            # Build column definition
                            col_def = f"  • {col_name}  →  {data_type.upper()}"

                            # Add length/precision
                            if max_length:
                                col_def += f"({max_length})"
                            elif num_precision and data_type in ['numeric', 'decimal']:
                                if num_scale:
                                    col_def += f"({num_precision},{num_scale})"
                                else:
                                    col_def += f"({num_precision})"

                            # Add constraints
                            if nullable == 'NO':
                                col_def += "  [NOT NULL]"
                            if default:
                                col_def += f"  [DEFAULT {default}]"

                            schema_info += col_def + "\n"
                        except (IndexError, TypeError) as e:
                            schema_info += f"  • (column data error: {e})\n"

                    schema_info += "\n"
                else:
                    schema_info += "⚠️  No columns found\n\n"

            except Exception as e:
                schema_info += f"⚠️  Error getting columns: {str(e)}\n\n"

            # ==========================================
            # GET PRIMARY KEY - Safe version
            # ==========================================
            try:
                # Use simple query that works on all PostgreSQL versions
                cursor.execute("""
                    SELECT c.column_name
                    FROM information_schema.table_constraints tc 
                    JOIN information_schema.constraint_column_usage AS ccu 
                        USING (constraint_schema, constraint_name) 
                    JOIN information_schema.columns AS c 
                        ON c.table_schema = tc.constraint_schema
                        AND tc.table_name = c.table_name 
                        AND ccu.column_name = c.column_name
                    WHERE tc.constraint_type = 'PRIMARY KEY' 
                    AND tc.table_schema = %s
                    AND tc.table_name = %s
                """, (self.schema, table_name))

                pk_result = cursor.fetchall()
                if pk_result and len(pk_result) > 0:
                    pk_columns = [row[0] for row in pk_result if len(row) > 0]
                    if pk_columns:
                        schema_info += f"PRIMARY KEY: {', '.join(pk_columns)}\n\n"
            except Exception as e:
                # Silently skip if PK query fails
                pass

            # ==========================================
            # GET FOREIGN KEYS - Safe version
            # ==========================================
            try:
                cursor.execute("""
                    SELECT
                        kcu.column_name,
                        ccu.table_name AS foreign_table_name,
                        ccu.column_name AS foreign_column_name
                    FROM information_schema.table_constraints AS tc
                    JOIN information_schema.key_column_usage AS kcu
                        ON tc.constraint_name = kcu.constraint_name
                        AND tc.table_schema = kcu.table_schema
                    JOIN information_schema.constraint_column_usage AS ccu
                        ON ccu.constraint_name = tc.constraint_name
                        AND ccu.table_schema = tc.table_schema
                    WHERE tc.constraint_type = 'FOREIGN KEY'
                    AND tc.table_name = %s
                    AND tc.table_schema = %s
                """, (table_name, self.schema))

                fk_result = cursor.fetchall()
                if fk_result and len(fk_result) > 0:
                    schema_info += "FOREIGN KEYS:\n"
                    schema_info += "-" * 60 + "\n"
                    for fk in fk_result:
                        try:
                            if len(fk) >= 3:
                                col_name = fk[0]
                                ref_table = fk[1]
                                ref_col = fk[2]
                                schema_info += f"  • {col_name} → {ref_table}.{ref_col}\n"
                        except (IndexError, TypeError):
                            pass
                    schema_info += "\n"
            except Exception as e:
                # Silently skip if FK query fails
                pass

            # ==========================================
            # GET INDEXES - Safe version
            # ==========================================
            try:
                cursor.execute("""
                    SELECT indexname
                    FROM pg_indexes
                    WHERE schemaname = %s
                    AND tablename = %s
                    AND indexname NOT LIKE '%%pkey'
                    ORDER BY indexname
                """, (self.schema, table_name))

                idx_result = cursor.fetchall()
                if idx_result and len(idx_result) > 0:
                    schema_info += "INDEXES:\n"
                    schema_info += "-" * 60 + "\n"
                    for idx in idx_result:
                        try:
                            if len(idx) > 0:
                                schema_info += f"  • {idx[0]}\n"
                        except (IndexError, TypeError):
                            pass
                    schema_info += "\n"
            except Exception as e:
                # Silently skip if index query fails
                pass

            # ==========================================
            # GET ROW COUNT - Safe version
            # ==========================================
            try:
                # Use COUNT(*) which is more reliable than pg_class
                cursor.execute(f"SELECT COUNT(*) FROM {self.schema}.{table_name}")
                count_result = cursor.fetchone()
                if count_result and len(count_result) > 0:
                    row_count = count_result[0]
                    schema_info += f"ROWS: {row_count:,}\n"
            except Exception as e:
                # Try estimate from pg_class
                try:
                    cursor.execute("""
                        SELECT n_live_tup 
                        FROM pg_stat_user_tables 
                        WHERE schemaname = %s 
                        AND relname = %s
                    """, (self.schema, table_name))
                    est_result = cursor.fetchone()
                    if est_result and len(est_result) > 0:
                        schema_info += f"ESTIMATED ROWS: ~{est_result[0]:,}\n"
                except:
                    pass

            return schema_info

        except Exception as e:
            # Return helpful error message
            error_msg = f"❌ Error retrieving schema for '{table_name}':\n"
            error_msg += f"   {str(e)}\n\n"
            error_msg += f"📍 Connection Info:\n"
            error_msg += f"   Schema: {self.schema}\n"
            error_msg += f"   Database: {self.database}\n"
            error_msg += f"   User: {self.user}\n\n"
            error_msg += f"💡 Troubleshooting:\n"
            error_msg += f"   1. Verify table exists: SELECT * FROM {self.schema}.{table_name} LIMIT 1;\n"
            error_msg += f"   2. Check schema is correct: SELECT table_schema FROM information_schema.tables WHERE table_name = '{table_name}';\n"
            error_msg += f"   3. Verify permissions: GRANT SELECT ON {self.schema}.{table_name} TO {self.user};\n"
            return error_msg
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def execute_query(self, sql: str) -> Tuple[List[str], List[List[Any]]]:
        """Execute SQL query and return results"""
        conn = self.connect()
        cursor = conn.cursor()

        try:
            cursor.execute(sql)

            # Check if query returns data
            if cursor.description is None:
                # Non-SELECT query (INSERT, UPDATE, DELETE, etc.)
                return [], []

            # Get column names
            columns = [desc[0] for desc in cursor.description]

            # Fetch all rows
            rows = cursor.fetchall()

            # Convert to list of lists
            data = [list(row) for row in rows]

            return columns, data

        except Exception as e:
            raise Exception(f"Query execution failed: {str(e)}")
        finally:
            cursor.close()
            conn.close()

    def health_check(self) -> bool:
        """Check PostgreSQL connection health"""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            cursor.close()
            conn.close()
            return result is not None and len(result) > 0
        except Exception as e:
            print(f"PostgreSQL health check failed: {e}")
            return False

    def get_connection_info(self) -> dict:
        """Get connection information"""
        return {
            "type": "postgresql",
            "host": self.host,
            "port": self.port,
            "database": self.database,
            "schema": self.schema,
            "user": self.user
        }