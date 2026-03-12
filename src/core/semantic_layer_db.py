import json
from typing import Dict, Any, List, Optional
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor


class SemanticLayerDB:
    """
    Manages semantic layer metadata in PostgreSQL
    """

    def __init__(self,
                 db_host: str = "localhost",
                 db_port: int = 5432,
                 db_name: str = "sqlatte_config",
                 db_user: str = "postgres",
                 db_password: str = "",
                 use_memory: bool = False):
        """
        Initialize Semantic Layer DB

        Args:
            db_host: PostgreSQL host
            db_port: PostgreSQL port
            db_name: Database name
            db_user: Database user
            db_password: Database password
            use_memory: Use SQLite in-memory (for testing)
        """
        self.use_memory = use_memory

        if use_memory:
            import sqlite3
            self.conn = sqlite3.connect(":memory:", check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self.db_type = "sqlite"
        else:
            self.conn = psycopg2.connect(
                host=db_host,
                port=db_port,
                dbname=db_name,
                user=db_user,
                password=db_password,
                gssencmode='disable',
            )
            self.db_type = "postgresql"

        self._create_tables()

    def _create_tables(self):
        """Create semantic layer tables if they don't exist"""
        cursor = self.conn.cursor()

        # SQLite vs PostgreSQL syntax
        if self.db_type == "sqlite":
            serial_type = "INTEGER PRIMARY KEY AUTOINCREMENT"
            timestamp_default = "DATETIME DEFAULT CURRENT_TIMESTAMP"
        else:
            serial_type = "SERIAL PRIMARY KEY"
            timestamp_default = "TIMESTAMP DEFAULT NOW()"

        # 1. Semantic Entities (Tables/Views with business context)
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS semantic_entities (
                id {serial_type},
                catalog VARCHAR(100),
                schema_name VARCHAR(100),
                table_name VARCHAR(100) NOT NULL,
                display_name VARCHAR(200),
                description TEXT,
                primary_key VARCHAR(100),
                entity_type VARCHAR(50) DEFAULT 'table',
                is_active BOOLEAN DEFAULT TRUE,
                created_at {timestamp_default},
                updated_at {timestamp_default}
            )
        """)

        # Add unique constraint if PostgreSQL
        if self.db_type == "postgresql":
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_semantic_entities_unique
                ON semantic_entities(catalog, schema_name, table_name)
            """)

        # 2. Semantic Columns (Column metadata)
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS semantic_columns (
                id {serial_type},
                entity_id INTEGER NOT NULL,
                column_name VARCHAR(100) NOT NULL,
                display_name VARCHAR(200),
                data_type VARCHAR(50),
                description TEXT,
                is_dimension BOOLEAN DEFAULT FALSE,
                is_metric BOOLEAN DEFAULT FALSE,
                format_type VARCHAR(50),
                aggregation_type VARCHAR(50),
                created_at {timestamp_default}
            )
        """)

        # Foreign key (PostgreSQL only)
        if self.db_type == "postgresql":
            cursor.execute("""
                DO $$ 
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint 
                        WHERE conname = 'fk_semantic_columns_entity'
                    ) THEN
                        ALTER TABLE semantic_columns 
                        ADD CONSTRAINT fk_semantic_columns_entity
                        FOREIGN KEY (entity_id) 
                        REFERENCES semantic_entities(id) 
                        ON DELETE CASCADE;
                    END IF;
                END $$;
            """)

        # 3. Semantic Relationships (Join definitions)
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS semantic_relationships (
                id {serial_type},
                name VARCHAR(200) NOT NULL,
                from_entity_id INTEGER NOT NULL,
                from_column VARCHAR(100) NOT NULL,
                to_entity_id INTEGER NOT NULL,
                to_column VARCHAR(100) NOT NULL,
                relationship_type VARCHAR(50),
                join_type VARCHAR(20) DEFAULT 'LEFT',
                description TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                created_at {timestamp_default}
            )
        """)

        # Foreign keys (PostgreSQL only)
        if self.db_type == "postgresql":
            cursor.execute("""
                DO $$ 
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint 
                        WHERE conname = 'fk_semantic_rel_from'
                    ) THEN
                        ALTER TABLE semantic_relationships
                        ADD CONSTRAINT fk_semantic_rel_from
                        FOREIGN KEY (from_entity_id)
                        REFERENCES semantic_entities(id)
                        ON DELETE CASCADE;
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint 
                        WHERE conname = 'fk_semantic_rel_to'
                    ) THEN
                        ALTER TABLE semantic_relationships
                        ADD CONSTRAINT fk_semantic_rel_to
                        FOREIGN KEY (to_entity_id)
                        REFERENCES semantic_entities(id)
                        ON DELETE CASCADE;
                    END IF;
                END $$;
            """)

        # 4. Semantic Metrics (Calculated fields)
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS semantic_metrics (
                id {serial_type},
                name VARCHAR(200) NOT NULL UNIQUE,
                display_name VARCHAR(200),
                description TEXT,
                sql_expression TEXT NOT NULL,
                format_type VARCHAR(50),
                category VARCHAR(100),
                requires_entities TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                created_at {timestamp_default}
            )
        """)

        self.conn.commit()
        cursor.close()

        print("✅ Semantic layer tables created/verified")

    # ==========================================
    # ENTITY MANAGEMENT
    # ==========================================

    def create_entity(self,
                      catalog: Optional[str],
                      schema_name: Optional[str],
                      table_name: str,
                      display_name: Optional[str] = None,
                      description: Optional[str] = None,
                      primary_key: Optional[str] = None,
                      entity_type: str = 'table') -> int:
        """
        Create a new semantic entity

        Returns:
            Entity ID
        """
        cursor = self.conn.cursor()

        if self.db_type == "sqlite":
            cursor.execute("""
                INSERT INTO semantic_entities 
                (catalog, schema_name, table_name, display_name, description, primary_key, entity_type)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (catalog, schema_name, table_name, display_name, description, primary_key, entity_type))
        else:
            cursor.execute("""
                INSERT INTO semantic_entities 
                (catalog, schema_name, table_name, display_name, description, primary_key, entity_type)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (catalog, schema_name, table_name, display_name, description, primary_key, entity_type))

        entity_id = cursor.fetchone()[0] if self.db_type == "postgresql" else cursor.lastrowid
        self.conn.commit()
        cursor.close()

        print(f"✅ Created entity: {display_name or table_name} (ID: {entity_id})")
        return entity_id

    def get_entities(self,
                     catalog: Optional[str] = None,
                     schema_name: Optional[str] = None,
                     active_only: bool = True) -> List[Dict[str, Any]]:
        """
        Get all semantic entities, optionally filtered by catalog/schema
        """
        if self.db_type == "postgresql":
            cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        else:
            cursor = self.conn.cursor()

        query = "SELECT * FROM semantic_entities WHERE 1=1"
        params = []

        if catalog:
            query += " AND catalog = ?"
            params.append(catalog)

        if schema_name:
            query += " AND schema_name = ?"
            params.append(schema_name)

        if active_only:
            query += " AND is_active = ?"
            params.append(True)

        query += " ORDER BY catalog, schema_name, table_name"

        if self.db_type == "postgresql":
            query = query.replace("?", "%s")

        cursor.execute(query, params)
        results = cursor.fetchall()
        cursor.close()

        if self.db_type == "sqlite":
            return [dict(row) for row in results]
        else:
            return results

    def get_entity(self, entity_id: int) -> Optional[Dict[str, Any]]:
        """Get a single entity by ID"""
        if self.db_type == "postgresql":
            cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        else:
            cursor = self.conn.cursor()

        param = "?" if self.db_type == "sqlite" else "%s"
        cursor.execute(f"SELECT * FROM semantic_entities WHERE id = {param}", (entity_id,))
        result = cursor.fetchone()
        cursor.close()

        if self.db_type == "sqlite" and result:
            return dict(result)
        return result

    def update_entity(self, entity_id: int, updates: Dict[str, Any]) -> bool:
        """Update an entity"""
        allowed_fields = ['display_name', 'description', 'primary_key', 'is_active']
        update_fields = {k: v for k, v in updates.items() if k in allowed_fields}

        if not update_fields:
            return False

        cursor = self.conn.cursor()

        set_clause = ", ".join([f"{k} = ?" for k in update_fields.keys()])
        if self.db_type == "postgresql":
            set_clause = ", ".join([f"{k} = %s" for k in update_fields.keys()])

        query = f"UPDATE semantic_entities SET {set_clause}, updated_at = {'CURRENT_TIMESTAMP' if self.db_type == 'sqlite' else 'NOW()'} WHERE id = {'?' if self.db_type == 'sqlite' else '%s'}"

        params = list(update_fields.values()) + [entity_id]
        cursor.execute(query, params)
        self.conn.commit()
        cursor.close()

        return True

    def delete_entity(self, entity_id: int) -> bool:
        """Delete an entity (soft delete by setting is_active=False)"""
        return self.update_entity(entity_id, {'is_active': False})

    # ==========================================
    # COLUMN MANAGEMENT
    # ==========================================

    def create_column(self,
                      entity_id: int,
                      column_name: str,
                      display_name: Optional[str] = None,
                      data_type: Optional[str] = None,
                      description: Optional[str] = None,
                      is_dimension: bool = False,
                      is_metric: bool = False,
                      format_type: Optional[str] = None,
                      aggregation_type: Optional[str] = None) -> int:
        """Create a semantic column"""
        cursor = self.conn.cursor()

        if self.db_type == "sqlite":
            cursor.execute("""
                INSERT INTO semantic_columns
                (entity_id, column_name, display_name, data_type, description, 
                 is_dimension, is_metric, format_type, aggregation_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (entity_id, column_name, display_name, data_type, description,
                  is_dimension, is_metric, format_type, aggregation_type))
        else:
            cursor.execute("""
                INSERT INTO semantic_columns
                (entity_id, column_name, display_name, data_type, description,
                 is_dimension, is_metric, format_type, aggregation_type)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (entity_id, column_name, display_name, data_type, description,
                  is_dimension, is_metric, format_type, aggregation_type))

        column_id = cursor.fetchone()[0] if self.db_type == "postgresql" else cursor.lastrowid
        self.conn.commit()
        cursor.close()

        return column_id

    def get_columns(self, entity_id: int) -> List[Dict[str, Any]]:
        """Get all columns for an entity"""
        if self.db_type == "postgresql":
            cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        else:
            cursor = self.conn.cursor()

        param = "?" if self.db_type == "sqlite" else "%s"
        cursor.execute(f"SELECT * FROM semantic_columns WHERE entity_id = {param} ORDER BY column_name", (entity_id,))
        results = cursor.fetchall()
        cursor.close()

        if self.db_type == "sqlite":
            return [dict(row) for row in results]
        return results

    # ==========================================
    # RELATIONSHIP MANAGEMENT
    # ==========================================

    def create_relationship(self,
                            name: str,
                            from_entity_id: int,
                            from_column: str,
                            to_entity_id: int,
                            to_column: str,
                            relationship_type: str = 'many_to_one',
                            join_type: str = 'LEFT',
                            description: Optional[str] = None) -> int:
        """Create a relationship (join definition)"""
        cursor = self.conn.cursor()

        if self.db_type == "sqlite":
            cursor.execute("""
                INSERT INTO semantic_relationships
                (name, from_entity_id, from_column, to_entity_id, to_column,
                 relationship_type, join_type, description)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (name, from_entity_id, from_column, to_entity_id, to_column,
                  relationship_type, join_type, description))
        else:
            cursor.execute("""
                INSERT INTO semantic_relationships
                (name, from_entity_id, from_column, to_entity_id, to_column,
                 relationship_type, join_type, description)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (name, from_entity_id, from_column, to_entity_id, to_column,
                  relationship_type, join_type, description))

        rel_id = cursor.fetchone()[0] if self.db_type == "postgresql" else cursor.lastrowid
        self.conn.commit()
        cursor.close()

        print(f"✅ Created relationship: {name} (ID: {rel_id})")
        return rel_id

    def get_relationships(self, entity_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get relationships, optionally filtered by entity"""
        if self.db_type == "postgresql":
            cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        else:
            cursor = self.conn.cursor()

        if entity_id:
            param = "?" if self.db_type == "sqlite" else "%s"
            cursor.execute(f"""
                SELECT r.*, 
                       e1.table_name as from_table,
                       e2.table_name as to_table
                FROM semantic_relationships r
                JOIN semantic_entities e1 ON r.from_entity_id = e1.id
                JOIN semantic_entities e2 ON r.to_entity_id = e2.id
                WHERE (r.from_entity_id = {param} OR r.to_entity_id = {param})
                  AND r.is_active = {'1' if self.db_type == 'sqlite' else 'TRUE'}
            """, (entity_id, entity_id))
        else:
            cursor.execute("""
                SELECT r.*,
                       e1.table_name as from_table,
                       e2.table_name as to_table
                FROM semantic_relationships r
                JOIN semantic_entities e1 ON r.from_entity_id = e1.id
                JOIN semantic_entities e2 ON r.to_entity_id = e2.id
                WHERE r.is_active = TRUE
            """)

        results = cursor.fetchall()
        cursor.close()

        if self.db_type == "sqlite":
            return [dict(row) for row in results]
        return results

    # ==========================================
    # METRIC MANAGEMENT
    # ==========================================

    def create_metric(self,
                      name: str,
                      sql_expression: str,
                      display_name: Optional[str] = None,
                      description: Optional[str] = None,
                      format_type: Optional[str] = None,
                      category: Optional[str] = None,
                      requires_entities: Optional[List[str]] = None) -> int:
        """Create a calculated metric"""
        cursor = self.conn.cursor()

        requires_json = json.dumps(requires_entities) if requires_entities else None

        if self.db_type == "sqlite":
            cursor.execute("""
                INSERT INTO semantic_metrics
                (name, display_name, description, sql_expression, format_type, category, requires_entities)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (name, display_name, description, sql_expression, format_type, category, requires_json))
        else:
            cursor.execute("""
                INSERT INTO semantic_metrics
                (name, display_name, description, sql_expression, format_type, category, requires_entities)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (name, display_name, description, sql_expression, format_type, category, requires_json))

        metric_id = cursor.fetchone()[0] if self.db_type == "postgresql" else cursor.lastrowid
        self.conn.commit()
        cursor.close()

        print(f"✅ Created metric: {display_name or name} (ID: {metric_id})")
        return metric_id

    def get_metrics(self, active_only: bool = True) -> List[Dict[str, Any]]:
        """Get all metrics"""
        if self.db_type == "postgresql":
            cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        else:
            cursor = self.conn.cursor()

        query = "SELECT * FROM semantic_metrics WHERE 1=1"
        if active_only:
            query += " AND is_active = TRUE"
        query += " ORDER BY category, name"

        cursor.execute(query)
        results = cursor.fetchall()
        cursor.close()

        if self.db_type == "sqlite":
            return [dict(row) for row in results]
        return results

    # ==========================================
    # SEMANTIC CONTEXT GENERATION
    # ==========================================

    def get_semantic_context(self,
                             catalog: Optional[str] = None,
                             schema_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Generate semantic context for LLM prompts

        Returns business-friendly metadata to enhance query understanding
        """
        entities = self.get_entities(catalog=catalog, schema_name=schema_name)
        relationships = self.get_relationships()
        metrics = self.get_metrics()

        context = {
            "entities": [],
            "relationships": [],
            "metrics": []
        }

        # Build entity context
        for entity in entities:
            columns = self.get_columns(entity['id'])

            dimensions = [c for c in columns if c.get('is_dimension')]
            entity_metrics = [c for c in columns if c.get('is_metric')]

            context["entities"].append({
                "name": entity['table_name'],
                "display_name": entity.get('display_name') or entity['table_name'],
                "description": entity.get('description'),
                "catalog": entity.get('catalog'),
                "schema": entity.get('schema_name'),
                "primary_key": entity.get('primary_key'),
                "dimensions": [{"name": d['column_name'], "display_name": d.get('display_name')} for d in dimensions],
                "metrics": [{"name": m['column_name'], "display_name": m.get('display_name')} for m in entity_metrics]
            })

        # Build relationship context
        for rel in relationships:
            context["relationships"].append({
                "name": rel['name'],
                "from": f"{rel.get('from_table')}.{rel['from_column']}",
                "to": f"{rel.get('to_table')}.{rel['to_column']}",
                "type": rel.get('relationship_type'),
                "join_type": rel.get('join_type')
            })

        # Build metrics context
        for metric in metrics:
            requires = json.loads(metric.get('requires_entities', '[]') or '[]')
            context["metrics"].append({
                "name": metric['name'],
                "display_name": metric.get('display_name'),
                "description": metric.get('description'),
                "sql": metric['sql_expression'],
                "format": metric.get('format_type'),
                "requires_entities": requires
            })

        return context

    def close(self):
        """Close database connection"""
        self.conn.close()


# Singleton instance
_semantic_layer_db = None


def get_semantic_layer_db(config: Optional[Dict[str, Any]] = None,
                          use_memory: bool = False) -> SemanticLayerDB:
    """
    Get singleton instance of Semantic Layer DB

    Args:
        config: Database configuration {'config_db': {'host': ..., 'port': ...}}
        use_memory: Use in-memory SQLite (for testing)
    """
    global _semantic_layer_db

    if _semantic_layer_db is None:
        if use_memory:
            _semantic_layer_db = SemanticLayerDB(use_memory=True)
        elif config:
            # Extract config_db (support both nested and flat)
            db_config = config.get('database', {}).get('config_db', {})
            if not db_config:
                db_config = config.get('config_db', {})

            # Support nested postgresql config
            if 'postgresql' in db_config:
                pg_config = db_config['postgresql']
            else:
                pg_config = db_config

            # Create instance with extracted config
            _semantic_layer_db = SemanticLayerDB(
                db_host=pg_config.get('host', 'localhost'),
                db_port=pg_config.get('port', 5432),
                db_name=pg_config.get('database', 'sqlatte_config'),
                db_user=pg_config.get('user', 'postgres'),
                db_password=pg_config.get('password', '')
            )
        else:
            # Default config
            _semantic_layer_db = SemanticLayerDB()

    return _semantic_layer_db