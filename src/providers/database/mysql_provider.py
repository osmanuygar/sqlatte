"""
MySQL Database Provider - Enhanced with Debug Logging
"""

import mysql.connector
from mysql.connector import Error
from typing import List, Tuple, Any
import socket
from src.core.db_provider import DatabaseProvider


class MySQLProvider(DatabaseProvider):
    """MySQL database provider implementation"""

    def __init__(self, config: dict):
        super().__init__(config)
        self.host = config.get('host', 'localhost')
        self.port = config.get('port', 3306)
        self.database = config.get('database', 'mysql')
        self.user = config.get('user', 'root')
        self.password = config.get('password', '')

        # Connection settings
        self.charset = config.get('charset', 'utf8mb4')
        self.use_unicode = config.get('use_unicode', True)
        self.autocommit = config.get('autocommit', True)

        self.connection = None

        # Debug: Log config
        print(f"\n🔍 [MySQL] Config loaded:")
        print(f"   Host: {self.host}")
        print(f"   Port: {self.port}")
        print(f"   Database: {self.database}")
        print(f"   User: {self.user}")
        print(f"   Password: {'*' * len(self.password) if self.password else '(empty)'}")

    def connect(self):
        """Establish MySQL connection with detailed error logging"""
        try:
            # Debug: Resolve host to IP
            try:
                resolved_ip = socket.gethostbyname(self.host)
                print(f"\n🌐 [MySQL] Host resolution:")
                print(f"   Input host: {self.host}")
                print(f"   Resolved IP: {resolved_ip}")
                print(f"   MySQL will see connection from: {resolved_ip}")
            except Exception as resolve_error:
                print(f"\n⚠️  [MySQL] Host resolution warning: {resolve_error}")
                resolved_ip = self.host

            # Attempt connection
            print(f"\n🔌 [MySQL] Connecting to {self.host}:{self.port}...")

            self.connection = mysql.connector.connect(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password,
                charset=self.charset,
                use_unicode=self.use_unicode,
                autocommit=self.autocommit,
                connect_timeout=10
            )

            print(f"✅ [MySQL] Connection successful!")
            return self.connection

        except Error as e:
            error_code = e.errno if hasattr(e, 'errno') else 'Unknown'
            error_msg = str(e)

            print(f"\n❌ [MySQL] Connection failed!")
            print(f"   Error code: {error_code}")
            print(f"   Error message: {error_msg}")

            # Parse error for helpful messages
            if '1045' in str(error_code) or 'Access denied' in error_msg:
                print(f"\n💡 [MySQL] Access Denied Troubleshooting:")
                print(f"   1. User '{self.user}' doesn't have permission from IP: {resolved_ip}")
                print(f"   2. Check MySQL grants:")
                print(f"      SELECT user, host FROM mysql.user WHERE user='{self.user}';")
                print(f"   3. Grant access from this IP:")
                print(f"      GRANT ALL PRIVILEGES ON {self.database}.* TO '{self.user}'@'{resolved_ip}' IDENTIFIED BY 'password';")
                print(f"      -- OR grant from anywhere (less secure):")
                print(f"      GRANT ALL PRIVILEGES ON {self.database}.* TO '{self.user}'@'%' IDENTIFIED BY 'password';")
                print(f"      FLUSH PRIVILEGES;")
            elif '2003' in str(error_code) or 'Can\'t connect' in error_msg:
                print(f"\n💡 [MySQL] Connection Refused:")
                print(f"   1. MySQL server not running")
                print(f"   2. Firewall blocking port {self.port}")
                print(f"   3. Wrong host: {self.host}")

            raise Exception(f"MySQL connection failed: {str(e)}")

    def get_tables(self) -> List[str]:
        """Get list of tables in the database"""
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
        """Get table schema with column details"""
        conn = self.connect()
        cursor = conn.cursor()

        try:
            # Get column information
            cursor.execute(f"DESCRIBE `{table_name}`")
            columns = cursor.fetchall()

            if not columns:
                return f"Table '{table_name}' not found in database '{self.database}'"

            schema_info = f"Table: {self.database}.{table_name}\nColumns:\n"

            primary_keys = []

            for col in columns:
                field, col_type, null, key, default, extra = col

                # Build column definition
                col_def = f"  - {field} ({col_type})"

                if null == 'NO':
                    col_def += " NOT NULL"

                if default is not None:
                    col_def += f" DEFAULT {default}"

                if extra:
                    col_def += f" {extra}"

                if key == 'PRI':
                    primary_keys.append(field)
                    col_def += " PRIMARY KEY"
                elif key == 'UNI':
                    col_def += " UNIQUE"
                elif key == 'MUL':
                    col_def += " INDEX"

                schema_info += col_def + "\n"

            # Get foreign key information
            cursor.execute(f"""
                SELECT 
                    COLUMN_NAME,
                    REFERENCED_TABLE_NAME,
                    REFERENCED_COLUMN_NAME
                FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
                WHERE TABLE_SCHEMA = %s
                AND TABLE_NAME = %s
                AND REFERENCED_TABLE_NAME IS NOT NULL
            """, (self.database, table_name))

            fk_info = cursor.fetchall()
            if fk_info:
                schema_info += "\nForeign Keys:\n"
                for fk in fk_info:
                    schema_info += f"  - {fk[0]} → {fk[1]}.{fk[2]}\n"

            # Get indexes
            cursor.execute(f"SHOW INDEX FROM `{table_name}`")
            indexes = cursor.fetchall()

            if indexes:
                # Group indexes by name
                index_dict = {}
                for idx in indexes:
                    index_name = idx[2]  # Key_name
                    column_name = idx[4]  # Column_name

                    if index_name not in ['PRIMARY'] and index_name not in index_dict:
                        index_dict[index_name] = []

                    if index_name not in ['PRIMARY']:
                        index_dict[index_name].append(column_name)

                if index_dict:
                    schema_info += "\nIndexes:\n"
                    for idx_name, cols in index_dict.items():
                        schema_info += f"  - {idx_name} ({', '.join(cols)})\n"

            # Get table status (engine, row count, etc.)
            cursor.execute(f"SHOW TABLE STATUS LIKE '{table_name}'")
            status = cursor.fetchone()
            if status:
                engine = status[1]  # Engine
                rows = status[4]  # Rows
                schema_info += f"\nTable Info:\n"
                schema_info += f"  - Engine: {engine}\n"
                schema_info += f"  - Approximate Rows: {rows}\n"

            return schema_info

        except Exception as e:
            return f"Could not fetch schema for {table_name}: {str(e)}"
        finally:
            cursor.close()
            conn.close()

    def execute_query(self, sql: str) -> Tuple[List[str], List[List[Any]]]:
        """Execute SQL query and return results"""
        conn = self.connect()
        cursor = conn.cursor()

        try:
            # Execute query
            cursor.execute(sql)

            # Get column names
            columns = [desc[0] for desc in cursor.description]

            # Fetch all rows
            rows = cursor.fetchall()

            # Convert to list of lists
            data = [list(row) for row in rows]

            return columns, data

        except Error as e:
            raise Exception(f"Query execution failed: {str(e)}")
        finally:
            cursor.close()
            conn.close()

    def health_check(self) -> bool:
        """Check MySQL connection health"""
        try:
            print(f"\n🏥 [MySQL] Health check starting...")
            conn = self.connect()
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            cursor.close()
            conn.close()

            if result:
                print(f"✅ [MySQL] Health check passed!")
                return True
            else:
                print(f"❌ [MySQL] Health check failed: No result")
                return False

        except Exception as e:
            print(f"❌ [MySQL] Health check failed: {e}")
            return False

    def get_connection_info(self) -> dict:
        """Get connection information (for display purposes)"""
        return {
            "type": "mysql",
            "host": self.host,
            "port": self.port,
            "database": self.database,
            "user": self.user,
            "charset": self.charset
        }