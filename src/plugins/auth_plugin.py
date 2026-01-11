"""
SQLatte Authentication Plugin - Enhanced Version (Backward Compatible)
With all standard widget features + config-based restrictions
"""

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import asyncio
from concurrent.futures import ThreadPoolExecutor

from src.plugins.base_plugin import BasePlugin
from src.plugins.session_manager import auth_session_manager
from src.core.conversation_manager import conversation_manager
import time
from src.core.provider_factory import ProviderFactory


class LoginRequest(BaseModel):
    """Login request model - backward compatible with simplified option"""
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
    Enhanced Authentication Plugin for SQLatte

    New Features:
    - Config-based DB restrictions (optional)
    - All standard widget features support
    - Backward compatible with existing setup

    Backward Compatible:
    - Works with existing login form
    - Optional config-based restrictions
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.session_manager = auth_session_manager
        self.executor = ThreadPoolExecutor(
            max_workers=config.get('max_workers', 40)  # Increased from 10
        )

        # Optional config-based restrictions (backward compatible)
        self.allowed_db_types = config.get('allowed_db_types', [])
        self.allowed_catalogs = config.get('allowed_catalogs', [])
        self.allowed_schemas = config.get('allowed_schemas', [])
        self.db_provider = config.get('db_provider', None)  # Optional
        self.db_host = config.get('db_host', None)  # Optional
        self.db_port = config.get('db_port', None)  # Optional

        print(f"🔐 Auth Plugin Enhanced:")
        print(f"   - Thread Pool: {self.executor._max_workers} workers")
        if self.allowed_catalogs:
            print(f"   - Allowed Catalogs: {self.allowed_catalogs}")
        if self.allowed_schemas:
            print(f"   - Allowed Schemas: {self.allowed_schemas}")

    def initialize(self, app: FastAPI) -> None:
        """Initialize auth plugin"""
        print(f"🔐 Initializing Enhanced Auth Plugin...")
        self.session_manager.start_cleanup_task()
        self.app = app

    def register_routes(self, app: FastAPI) -> None:
        """Register authentication routes"""

        @app.get("/auth/config")
        async def get_auth_config():
            """
            NEW ENDPOINT: Return server config for client-side restrictions

            This is optional - if no restrictions configured, returns empty lists
            """
            return JSONResponse({
                "allowed_db_types": self.allowed_db_types,
                "allowed_catalogs": self.allowed_catalogs,
                "allowed_schemas": self.allowed_schemas,
                "db_provider": self.db_provider,
                "db_host": self.db_host,
                "db_port": self.db_port
            })

        @app.post("/auth/login")
        async def login(request: LoginRequest):
            """
            Login endpoint - Validates credentials and creates session

            ENHANCED: Optionally validates against allowed catalogs/schemas
            """
            try:
                # Validate restrictions if configured
                if self.allowed_catalogs and request.catalog not in self.allowed_catalogs:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Catalog '{request.catalog}' not allowed"
                    )

                if self.allowed_schemas and request.schema not in self.allowed_schemas:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Schema '{request.schema}' not allowed"
                    )

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
                    },
                    # NEW: Include user_info for frontend
                    "user_info": {
                        "username": request.username,
                        "catalog": request.catalog,
                        "schema": request.schema
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

            return {
                "valid": is_valid,
                "session_id": request.session_id
            }

        @app.get("/auth/session-info")
        async def get_session_info(session_id: str = Header(..., alias="X-Session-ID")):
            """Get current session information"""
            session = self.session_manager.get_session(session_id)

            if not session:
                raise HTTPException(
                    status_code=401,
                    detail="Session expired or invalid"
                )

            return {
                "username": session.username,
                "created_at": session.created_at.isoformat(),
                "last_activity": session.last_activity.isoformat()
            }

        @app.get("/auth/stats")
        async def get_auth_stats():
            """Get authentication statistics"""
            return {
                "active_sessions": self.session_manager.get_active_session_count(),
                "total_sessions": len(self.session_manager.sessions)
            }

        @app.get("/auth/tables")
        async def get_tables(session_id: str = Header(..., alias="X-Session-ID")):
            """Get available tables for authenticated user"""
            try:
                session = self.session_manager.get_session(session_id)

                if not session:
                    raise HTTPException(
                        status_code=401,
                        detail="Session expired or invalid"
                    )

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
            """Get schema for a specific table"""
            try:
                session = self.session_manager.get_session(session_id)

                if not session:
                    raise HTTPException(
                        status_code=401,
                        detail="Session expired or invalid"
                    )

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

        @app.post("/auth/schema/multiple")
        async def get_multiple_schemas(
            request: Dict[str, List[str]],
            session_id: str = Header(..., alias="X-Session-ID")
        ):
            """
            NEW ENDPOINT: Get combined schema for multiple tables
            """
            try:
                session = self.session_manager.get_session(session_id)

                if not session:
                    raise HTTPException(
                        status_code=401,
                        detail="Session expired or invalid"
                    )

                tables = request.get('tables', [])
                if not tables:
                    raise HTTPException(
                        status_code=400,
                        detail="No tables provided"
                    )

                loop = asyncio.get_event_loop()
                schemas = []

                for table in tables:
                    schema = await loop.run_in_executor(
                        self.executor,
                        self._get_schema_for_session,
                        session.db_config,
                        table
                    )
                    schemas.append(f"Table: {table}\n{schema}")

                combined = "\n\n".join(schemas)

                return {
                    "combined_schema": combined
                }

            except HTTPException:
                raise
            except Exception as e:
                print(f"❌ Error loading schemas: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to load schemas: {str(e)}"
                )

        @app.post("/auth/query")
        async def execute_query(
                request: dict,
                session_id: str = Header(..., alias="X-Session-ID")
        ):
            """
            Execute SQL query with CONVERSATION MEMORY
            """
            start_time = time.time()
            session = None
            selected_tables = []
            try:
                from src.core.conversation_manager import conversation_manager
                from src.core.query_history import query_history

                # 1. Validate auth session
                session = self.session_manager.get_session(session_id)
                if not session:
                    raise HTTPException(401, "Session expired or invalid")

                question = request.get('question', '')
                table_schema = request.get('table_schema', '') or request.get('schema', '')

                if not question:
                    raise HTTPException(400, "Question is required")

                # Extract tables from schema
                if table_schema:
                    for line in table_schema.split('\n'):
                        if line.startswith('Table:'):
                            table_name = line.replace('Table:', '').strip()
                            if '.' in table_name:
                                table_name = table_name.split('.')[-1]
                            selected_tables.append(table_name)

                # 2. Get or create conversation session
                if not session.conversation_id:
                    conv_id = conversation_manager.create_session()
                    session.conversation_id = conv_id
                    print(f"🆕 Conversation session created: {conv_id[:8]}... for user: {session.username}")
                else:
                    conv_id = session.conversation_id

                # 3. Add user message to conversation
                conversation_manager.add_message(
                    conv_id,
                    role="user",
                    content=question,
                    metadata={"username": session.username}
                )

                # 4. Execute query WITH conversation_id
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    self.executor,
                    self._execute_query_for_session,
                    session.db_config,
                    question,
                    table_schema,
                    conv_id  # 👈 CONVERSATION ID GEÇIR
                )
                execution_time = (time.time() - start_time) * 1000

                # 5. Add assistant response to conversation
                if "error" in result:
                    content = result["error"]
                    metadata = {"type": "error"}
                    query_history.add_query(
                        session_id=session_id,
                        question=question,
                        sql="",
                        tables=selected_tables,
                        row_count=0,
                        execution_time_ms=execution_time,
                        success=False,
                        error_message=result["error"],
                        widget_type="auth",
                        user_id=session.username
                    )
                elif "sql" in result:
                    content = f"Generated SQL with {len(result.get('data', []))} rows"
                    metadata = {
                        "type": "sql",
                        "sql": result["sql"],
                        "row_count": len(result.get("data", []))
                    }
                    query_history.add_query(
                        session_id=session_id,
                        question=question,
                        sql=result["sql"],
                        tables=selected_tables,
                        row_count=len(result.get("data", [])),
                        execution_time_ms=execution_time,
                        success=True,
                        widget_type="auth",
                        user_id=session.username
                    )
                elif "response_type" in result and result["response_type"] == "chat":
                    content = result["message"]
                    metadata = {"type": "chat"}
                else:
                    content = str(result)
                    metadata = {"type": "unknown"}

                conversation_manager.add_message(
                    conv_id,
                    role="assistant",
                    content=content,
                    metadata=metadata
                )

                # 6. Return result
                result["conversation_id"] = conv_id
                return result

            except HTTPException:
                raise
            except Exception as e:
                execution_time = (time.time() - start_time) * 1000

                # ← YENİ: Track unexpected errors
                from src.core.query_history import query_history
                query_history.add_query(
                    session_id=session_id,
                    question=request.get('question', ''),
                    sql="",
                    tables=[],
                    row_count=0,
                    execution_time_ms=execution_time,
                    success=False,
                    error_message=str(e),
                    widget_type="auth",
                    user_id=session.username if 'session' in locals() else None
                )

                print(f"❌ Auth query error: {e}")
                import traceback
                traceback.print_exc()
                raise HTTPException(
                    status_code=500,
                    detail=f"Query execution failed: {str(e)}"
                )

        @app.get("/auth/conversation/history")
        async def get_conversation_history(
                session_id: str = Header(..., alias="X-Session-ID"),
                limit: int = 50
        ):
            """Get conversation history for authenticated user"""
            session = self.session_manager.get_session(session_id)
            if not session:
                raise HTTPException(401, "Session expired")

            if not session.conversation_id:
                return {"messages": [], "total": 0}

            history = conversation_manager.get_session_history(session.conversation_id)

            return {
                "messages": history[-limit:] if limit else history,
                "total": len(history),
                "conversation_id": session.conversation_id
            }

        # YENİ ENDPOINT: Clear conversation
        @app.post("/auth/conversation/clear")
        async def clear_conversation(
                session_id: str = Header(..., alias="X-Session-ID")
        ):
            """Clear conversation history"""
            session = self.session_manager.get_session(session_id)
            if not session:
                raise HTTPException(401, "Session expired")

            if session.conversation_id:
                conversation_manager.clear_session(session.conversation_id)
                print(f"🗑️ Conversation cleared for: {session.username}")

            return {"message": "Conversation cleared", "success": True}


    def _build_db_config(self, request: LoginRequest) -> Dict[str, Any]:
        """Build database config from login request"""
        config = {
            'host': request.host,
            'port': request.port,
            'user': request.username,
            'password': request.password,
        }

        # Database-specific fields
        if request.database_type == 'trino':
            if request.catalog:
                config['catalog'] = request.catalog
            if request.schema:
                config['schema'] = request.schema
            config['http_scheme'] = request.http_scheme

        elif request.database_type == 'postgresql':
            if request.database:
                config['database'] = request.database
            else:
                config['database'] = 'postgres'

        elif request.database_type == 'mysql':
            if request.database:
                config['database'] = request.database
            else:
                config['database'] = 'mysql'

        return config

    def _test_db_connection(
        self,
        db_type: str,
        db_config: Dict[str, Any]
    ) -> bool:
        """Test database connection"""
        try:
            wrapped_config = {
                'database': {
                    'provider': db_type,
                    db_type: db_config
                }
            }

            db_provider = ProviderFactory.create_db_provider(wrapped_config)
            tables = db_provider.get_tables()

            print(f"✅ Connection test successful: {len(tables)} tables found")
            return True

        except Exception as e:
            print(f"❌ Connection test failed: {e}")
            return False

    def _get_tables_for_session(self, db_config: Dict[str, Any]) -> List[str]:
        """Get tables for a session's DB connection"""
        try:
            wrapped_config = {'database': db_config}
            db_provider = ProviderFactory.create_db_provider(wrapped_config)
            tables = db_provider.get_tables()

            print(f"📊 Retrieved {len(tables)} tables")
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
        """Get schema for a specific table"""
        try:
            wrapped_config = {'database': db_config}
            db_provider = ProviderFactory.create_db_provider(wrapped_config)
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
            table_schema: str,
            conversation_id: str = None  # 👈 YENİ PARAMETRE
    ) -> Dict[str, Any]:
        """
        Execute query with CONVERSATION CONTEXT support
        """
        try:
            from src.core.config_manager import config_manager
            from src.core.conversation_manager import conversation_manager  # 👈 YENİ

            wrapped_db_config = {'database': db_config}
            db_provider = ProviderFactory.create_db_provider(wrapped_db_config)

            llm_config = config_manager.get_config()
            llm_provider = ProviderFactory.create_llm_provider(llm_config)

            print(f"🤖 Processing query: {question[:50]}...")

            schema_info = table_schema if table_schema else "No schema provided."
            intent_result = llm_provider.determine_intent(question, schema_info)

            print(f"🎯 Intent: {intent_result['intent']} (confidence: {intent_result['confidence']})")

            if intent_result["intent"] == "sql" and intent_result["confidence"] > 0.6:
                if schema_info == "No schema provided.":
                    return {
                        "error": "☕ Please select one or more tables first to query your data."
                    }

                # 👇 YENİ: Get conversation context
                enhanced_question = question
                if conversation_id:
                    conv_context = conversation_manager.get_conversation_context(conversation_id)
                    if len(conv_context) > 1:  # Has history
                        context_summary = "\n\nRecent conversation:\n"
                        for msg in conv_context[-5:]:  # Last 5 messages
                            if msg['role'] == 'user':
                                context_summary += f"User: {msg['content']}\n"
                            elif msg['role'] == 'assistant':
                                # Truncate long responses
                                content = msg['content'][:100]
                                context_summary += f"Assistant: {content}...\n"

                        enhanced_question = f"{question}\n\nContext from previous messages: {context_summary}"
                        print(f"💬 Using conversation context ({len(conv_context)} messages)")

                # Generate SQL with context
                sql_query, explanation = llm_provider.generate_sql(enhanced_question, schema_info)

                print(f"📝 Generated SQL: {sql_query[:100]}...")

                if not sql_query:
                    return {
                        "error": "Failed to generate SQL query. Please try rephrasing your question."
                    }

                # Execute query
                columns, data = db_provider.execute_query(sql_query)

                print(f"✅ Query executed: {len(data)} rows returned")

                return {
                    "sql": sql_query,
                    "columns": columns,
                    "data": data,
                    "explanation": explanation,
                    "query_id": None
                }

            else:
                # 👇 YENİ: Chat response with context
                enhanced_question = question
                if conversation_id:
                    conv_context = conversation_manager.get_conversation_context(conversation_id)
                    if len(conv_context) > 1:
                        context_text = "Previous conversation:\n"
                        for msg in conv_context[-5:]:
                            role_label = "User" if msg['role'] == 'user' else "Assistant"
                            context_text += f"{role_label}: {msg['content']}\n"

                        enhanced_question = f"{context_text}\n\nCurrent question: {question}"
                        print(f"💬 Chat with context ({len(conv_context)} messages)")

                chat_response = llm_provider.generate_chat_response(enhanced_question, schema_info)

                return {
                    "response_type": "chat",
                    "message": chat_response,
                    "intent_info": intent_result
                }

        except Exception as e:
            print(f"❌ Query execution error: {e}")
            import traceback
            traceback.print_exc()

            return {
                "response_type": "chat",
                "message": f"❌ Error executing query: {str(e)}",
                "error": True
            }

    def shutdown(self) -> None:
        """Cleanup on shutdown"""
        print("🔐 Shutting down Enhanced Auth Plugin...")
        self.session_manager.stop_cleanup_task()
        self.executor.shutdown(wait=True)


def create_auth_plugin(config: Dict[str, Any]) -> AuthPlugin:
    """
    Factory function to create auth plugin (backward compatible)
    """
    return AuthPlugin(config)