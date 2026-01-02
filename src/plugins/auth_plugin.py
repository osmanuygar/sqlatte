"""
SQLatte Authentication Plugin
Enables user authentication with session-based DB connections
"""

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any
import asyncio
from concurrent.futures import ThreadPoolExecutor

from src.plugins.base_plugin import BasePlugin
from src.plugins.session_manager import auth_session_manager
from src.core.provider_factory import ProviderFactory


class LoginRequest(BaseModel):
    """Login request model"""
    username: str
    password: str
    database_type: str  # 'trino', 'postgresql', 'mysql'
    host: str
    port: int
    catalog: Optional[str] = None  # Trino
    schema: Optional[str] = 'default'
    database: Optional[str] = None  # PostgreSQL, MySQL
    http_scheme: Optional[str] = 'https'  # Trino


class ValidateSessionRequest(BaseModel):
    """Session validation request"""
    session_id: str


class AuthPlugin(BasePlugin):
    """
    Authentication Plugin for SQLatte

    Features:
    - User login with DB credentials
    - Session-based authentication
    - Per-session database connections
    - Thread-safe connection pooling
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.session_manager = auth_session_manager
        self.executor = ThreadPoolExecutor(
            max_workers=config.get('max_workers', 10)
        )

    def initialize(self, app: FastAPI) -> None:
        """Initialize auth plugin"""
        print(f"🔐 Initializing Auth Plugin...")

        # Start session cleanup task
        self.session_manager.start_cleanup_task()

        # Store app reference
        self.app = app

    def register_routes(self, app: FastAPI) -> None:
        """Register authentication routes"""

        @app.post("/auth/login")
        async def login(request: LoginRequest):
            """
            Login endpoint - Validates credentials and creates session

            Returns:
                {
                    "success": true,
                    "session_id": "...",
                    "message": "Login successful"
                }
            """
            try:
                # Build database config from login request
                db_config = self._build_db_config(request)

                # Test connection in thread pool (non-blocking)
                loop = asyncio.get_event_loop()
                is_valid = await loop.run_in_executor(
                    self.executor,
                    self._test_db_connection,
                    request.database_type,
                    db_config
                )

                if not is_valid:
                    raise HTTPException(
                        status_code=401,
                        detail="Invalid credentials or connection failed"
                    )

                # Create session
                session_id = self.session_manager.create_session(
                    username=request.username,
                    db_config={
                        'provider': request.database_type,
                        request.database_type: db_config
                    }
                )

                return {
                    "success": True,
                    "session_id": session_id,
                    "message": "Login successful",
                    "user": {
                        "username": request.username,
                        "database_type": request.database_type,
                        "host": request.host
                    }
                }

            except HTTPException:
                raise
            except Exception as e:
                print(f"❌ Login error: {e}")
                import traceback
                traceback.print_exc()
                raise HTTPException(
                    status_code=500,
                    detail=f"Login failed: {str(e)}"
                )

        @app.post("/auth/logout")
        async def logout(session_id: str = Header(..., alias="X-Session-ID")):
            """Logout - Destroy session"""
            success = self.session_manager.destroy_session(session_id)

            if not success:
                raise HTTPException(
                    status_code=404,
                    detail="Session not found"
                )

            return {
                "success": True,
                "message": "Logged out successfully"
            }

        @app.post("/auth/validate")
        async def validate_session(request: ValidateSessionRequest):
            """Validate if session is still active"""
            is_valid = self.session_manager.validate_session(request.session_id)

            if not is_valid:
                return {
                    "valid": False,
                    "message": "Session expired or invalid"
                }

            session = self.session_manager.get_session(request.session_id)

            return {
                "valid": True,
                "message": "Session is active",
                "user": {
                    "username": session.username,
                    "created_at": session.created_at.isoformat(),
                    "last_activity": session.last_activity.isoformat()
                }
            }

        @app.get("/auth/session-info")
        async def get_session_info(session_id: str = Header(..., alias="X-Session-ID")):
            """Get session information"""
            session = self.session_manager.get_session(session_id)

            if not session:
                raise HTTPException(
                    status_code=404,
                    detail="Session not found or expired"
                )

            return session.to_dict()

        @app.get("/auth/stats")
        async def auth_stats():
            """Get authentication statistics (admin)"""
            return self.session_manager.get_stats()

        @app.get("/auth/tables")
        async def get_tables(session_id: str = Header(..., alias="X-Session-ID")):
            """
            Get list of tables for authenticated user's database

            Headers:
                X-Session-ID: Session identifier from login

            Returns:
                {"tables": ["table1", "table2", ...]}
            """
            try:
                # Get session
                session = self.session_manager.get_session(session_id)

                if not session:
                    raise HTTPException(
                        status_code=401,
                        detail="Session expired or invalid"
                    )

                # Get DB provider for this session
                loop = asyncio.get_event_loop()
                tables = await loop.run_in_executor(
                    self.executor,
                    self._get_tables_for_session,
                    session.db_config
                )

                return {"tables": tables}

            except HTTPException:
                raise
            except Exception as e:
                print(f"❌ Error loading tables: {e}")
                import traceback
                traceback.print_exc()
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to load tables: {str(e)}"
                )

        @app.get("/auth/schema/{table_name}")
        async def get_schema(
            table_name: str,
            session_id: str = Header(..., alias="X-Session-ID")
        ):
            """
            Get schema for a specific table

            Headers:
                X-Session-ID: Session identifier from login

            Returns:
                {"table": "table_name", "schema": "..."}
            """
            try:
                # Get session
                session = self.session_manager.get_session(session_id)

                if not session:
                    raise HTTPException(
                        status_code=401,
                        detail="Session expired or invalid"
                    )

                # Get schema
                loop = asyncio.get_event_loop()
                schema = await loop.run_in_executor(
                    self.executor,
                    self._get_schema_for_session,
                    session.db_config,
                    table_name
                )

                return {
                    "table": table_name,
                    "schema": schema
                }

            except HTTPException:
                raise
            except Exception as e:
                print(f"❌ Error loading schema: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to load schema: {str(e)}"
                )

        @app.post("/auth/query")
        async def execute_query(
            request: dict,
            session_id: str = Header(..., alias="X-Session-ID")
        ):
            """
            Execute SQL query with user's database connection

            Headers:
                X-Session-ID: Session identifier from login

            Request Body:
                {
                    "question": "natural language question",
                    "table_schema": "schema information"
                }

            Returns:
                {
                    "response_type": "sql" or "chat",
                    "sql": "...",
                    "columns": [...],
                    "data": [...],
                    "explanation": "...",
                    ...
                }
            """
            try:
                # Get session
                session = self.session_manager.get_session(session_id)

                if not session:
                    raise HTTPException(
                        status_code=401,
                        detail="Session expired or invalid"
                    )

                # Extract request data
                question = request.get('question', '')
                table_schema = request.get('table_schema', '')

                if not question:
                    raise HTTPException(
                        status_code=400,
                        detail="Question is required"
                    )

                # Execute query
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    self.executor,
                    self._execute_query_for_session,
                    session.db_config,
                    question,
                    table_schema
                )

                return result

            except HTTPException:
                raise
            except Exception as e:
                print(f"❌ Error executing query: {e}")
                import traceback
                traceback.print_exc()
                raise HTTPException(
                    status_code=500,
                    detail=f"Query execution failed: {str(e)}"
                )

        print(f"   ✅ Auth routes registered:")
        print(f"      POST /auth/login")
        print(f"      POST /auth/logout")
        print(f"      POST /auth/validate")
        print(f"      GET  /auth/session-info")
        print(f"      GET  /auth/stats")
        print(f"      GET  /auth/tables")
        print(f"      GET  /auth/schema/{{table_name}}")
        print(f"      POST /auth/query")

    def _build_db_config(self, request: LoginRequest) -> Dict[str, Any]:
        """Build database config from login request"""
        config = {
            'host': request.host,
            'port': request.port,
            'user': request.username,
            'password': request.password,
        }

        if request.database_type == 'trino':
            config.update({
                'catalog': request.catalog or 'hive',
                'schema': request.schema or 'default',
                'http_scheme': request.http_scheme or 'https'
            })
        elif request.database_type in ['postgresql', 'mysql']:
            config.update({
                'database': request.database or request.username,
                'schema': request.schema or 'public'
            })

        return config

    def _test_db_connection(
        self,
        provider_type: str,
        db_config: Dict[str, Any]
    ) -> bool:
        """
        Test database connection (runs in thread pool)

        Args:
            provider_type: 'trino', 'postgresql', 'mysql'
            db_config: Database configuration

        Returns:
            True if connection successful
        """
        try:
            # Create test config
            test_config = {
                'database': {
                    'provider': provider_type,
                    provider_type: db_config
                }
            }

            # Create provider and test
            db_provider = ProviderFactory.create_db_provider(test_config)
            is_healthy = db_provider.health_check()

            print(f"🔍 Connection test: {provider_type} @ {db_config.get('host')} = {is_healthy}")

            return is_healthy

        except Exception as e:
            print(f"❌ Connection test failed: {e}")
            return False

    def _get_tables_for_session(self, db_config: Dict[str, Any]) -> list:
        """
        Get list of tables for a session's DB connection

        Args:
            db_config: Database configuration from session
                      Format: {'provider': 'trino', 'trino': {...}}

        Returns:
            List of table names
        """
        try:
            # Wrap config in 'database' key for ProviderFactory
            wrapped_config = {'database': db_config}

            # Create DB provider
            db_provider = ProviderFactory.create_db_provider(wrapped_config)

            # Get tables
            tables = db_provider.get_tables()

            print(f"📊 Retrieved {len(tables)} tables for user")

            return tables

        except Exception as e:
            print(f"❌ Failed to get tables: {e}")
            import traceback
            traceback.print_exc()
            raise

    def _get_schema_for_session(
        self,
        db_config: Dict[str, Any],
        table_name: str
    ) -> str:
        """
        Get schema for a specific table

        Args:
            db_config: Database configuration from session
                      Format: {'provider': 'trino', 'trino': {...}}
            table_name: Name of the table

        Returns:
            Schema information as string
        """
        try:
            # Wrap config in 'database' key for ProviderFactory
            wrapped_config = {'database': db_config}

            # Create DB provider
            db_provider = ProviderFactory.create_db_provider(wrapped_config)

            # Get schema
            schema = db_provider.get_table_schema(table_name)

            print(f"📋 Retrieved schema for table: {table_name}")

            return schema

        except Exception as e:
            print(f"❌ Failed to get schema for {table_name}: {e}")
            import traceback
            traceback.print_exc()
            raise

    def _execute_query_for_session(
        self,
        db_config: Dict[str, Any],
        question: str,
        table_schema: str
    ) -> Dict[str, Any]:
        """
        Execute query for a session's DB connection

        Args:
            db_config: Database configuration from session
                      Format: {'provider': 'trino', 'trino': {...}}
            question: Natural language question
            table_schema: Schema information

        Returns:
            Query result dictionary
        """
        try:
            # Import here to avoid circular dependency
            from src.core.config_manager import config_manager

            # Wrap DB config
            wrapped_db_config = {'database': db_config}

            # Create DB provider for this session
            db_provider = ProviderFactory.create_db_provider(wrapped_db_config)

            # Get LLM provider from global config
            llm_config = config_manager.get_config()
            llm_provider = ProviderFactory.create_llm_provider(llm_config)

            print(f"🤖 Processing query: {question[:50]}...")

            # Determine intent
            schema_info = table_schema if table_schema else "No schema provided."
            intent_result = llm_provider.determine_intent(question, schema_info)

            print(f"🎯 Intent: {intent_result['intent']} (confidence: {intent_result['confidence']})")

            # Route based on intent
            if intent_result["intent"] == "sql" and intent_result["confidence"] > 0.6:
                if schema_info == "No schema provided.":
                    return {
                        "response_type": "chat",
                        "message": "☕ Please select one or more tables first to query your data.",
                        "intent_info": intent_result
                    }

                # Generate SQL
                sql_query, explanation = llm_provider.generate_sql(question, schema_info)

                print(f"📝 Generated SQL: {sql_query[:100]}...")

                if not sql_query:
                    return {
                        "response_type": "chat",
                        "message": "Failed to generate SQL query. Please try rephrasing your question.",
                        "intent_info": intent_result
                    }

                # Execute query
                columns, data = db_provider.execute_query(sql_query)

                print(f"✅ Query executed: {len(data)} rows returned")

                return {
                    "response_type": "sql",
                    "sql": sql_query,
                    "columns": columns,
                    "data": data,
                    "row_count": len(data),
                    "explanation": explanation
                }

            else:
                # Chat response
                chat_response = llm_provider.generate_chat_response(question, schema_info)

                return {
                    "response_type": "chat",
                    "message": chat_response,
                    "intent_info": intent_result
                }

        except Exception as e:
            print(f"❌ Query execution error: {e}")
            import traceback
            traceback.print_exc()

            # Return error as chat response
            return {
                "response_type": "chat",
                "message": f"❌ Error executing query: {str(e)}",
                "error": True
            }

    def shutdown(self) -> None:
        """Cleanup on shutdown"""
        print("🔐 Shutting down Auth Plugin...")
        self.session_manager.stop_cleanup_task()
        self.executor.shutdown(wait=True)


def create_auth_plugin(config: Dict[str, Any]) -> AuthPlugin:
    """Factory function to create auth plugin"""
    return AuthPlugin(config)