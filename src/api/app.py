"""
SQLatte API - Optimized with Async Processing & Thread Pool
"""

import time
import asyncio
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Any, Optional
import os
import sys

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Now import from src
from src.core.config_manager import config_manager
from src.core.provider_factory import ProviderFactory
from src.core.conversation_manager import conversation_manager
from src.core.query_history import query_history
from src.api.admin_routes import router as admin_router
from src.api.demo_routes import router as demo_router
from src.api.analytics_routes import router as analytics_router


# Plugin system
from src.plugins.base_plugin import plugin_manager
from src.plugins.auth_plugin import create_auth_plugin

# Load configuration from file
CONFIG_PATH = os.path.join(PROJECT_ROOT, 'config', 'config.yaml')
config = config_manager.load_from_file(CONFIG_PATH)

# ============================================
# THREAD POOL FOR ASYNC OPERATIONS
# ============================================
# Increased workers for concurrent requests
MAIN_EXECUTOR = ThreadPoolExecutor(
    max_workers=20,  # 👈 INCREASED from implicit default
    thread_name_prefix="sqlatte-main"
)

print(f"✅ Thread pool initialized: 20 workers")

# Create providers - using function to allow reloading
def get_current_providers():
    """Get current LLM and DB providers"""
    current_config = config_manager.get_config()
    llm = ProviderFactory.create_llm_provider(current_config)
    db = ProviderFactory.create_db_provider(current_config)
    return llm, db

# Initialize providers
llm_provider, db_provider = get_current_providers()

print(f"✅ Initial providers loaded:")
print(f"   LLM: {llm_provider.get_model_name()}")
print(f"   DB: {db_provider.get_connection_info()['type']}")

# ============================================
# DYNAMIC PROVIDER RELOAD
# ============================================
def reload_providers():
    """
    Reload providers with current configuration
    This updates the global llm_provider and db_provider
    """
    global llm_provider, db_provider

    print("\n🔄 Reloading providers...")
    current_config = config_manager.get_config()

    try:
        # Recreate LLM provider
        new_llm = ProviderFactory.create_llm_provider(current_config)
        llm_provider = new_llm
        print(f"✅ LLM provider reloaded: {llm_provider.get_model_name()}")
    except Exception as e:
        print(f"⚠️ Failed to reload LLM provider: {e}")
        raise

    try:
        # Recreate Database provider
        new_db = ProviderFactory.create_db_provider(current_config)
        db_provider = new_db
        print(f"✅ Database provider reloaded: {db_provider.get_connection_info()['type']}")
    except Exception as e:
        print(f"⚠️ Failed to reload Database provider: {e}")
        raise

    print("🎉 Provider reload complete!\n")

    return {
        "llm": {
            "provider": current_config['llm']['provider'],
            "model": llm_provider.get_model_name()
        },
        "database": {
            "provider": current_config['database']['provider'],
            "info": db_provider.get_connection_info()
        }
    }


# ============================================
# PLUGIN SYSTEM INITIALIZATION
# ============================================
def initialize_plugins(app: FastAPI):
    """Initialize and register plugins"""
    plugins_config = config.get('plugins', {})

    # Auth plugin
    if plugins_config.get('auth', {}).get('enabled', False):
        print("\n🔐 Initializing Auth Plugin...")
        auth_config = plugins_config['auth']
        auth_plugin = create_auth_plugin(auth_config)
        plugin_manager.register_plugin(auth_plugin)

    # Initialize all registered plugins
    plugin_manager.initialize_all(app)

    print("✅ Plugin system initialized\n")


# Initialize FastAPI
app = FastAPI(
    title=config['app']['name'],
    version=config['app']['version'],
    description="☕ Serving perfect SQL queries with async processing"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=config['cors']['allow_origins'],
    allow_credentials=config['cors']['allow_credentials'],
    allow_methods=config['cors']['allow_methods'],
    allow_headers=config['cors']['allow_headers'],
)

# Mount static files (CSS, JS)
STATIC_DIR = os.path.join(PROJECT_ROOT, 'frontend', 'static')
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Initialize plugin system
initialize_plugins(app)

# Include routers
app.include_router(admin_router)
app.include_router(demo_router)
app.include_router(analytics_router)

# ============================================
# REQUEST/RESPONSE MODELS
# ============================================

class QueryRequest(BaseModel):
    question: str
    table_schema: str = ""
    session_id: Optional[str] = None


class SQLQueryResponse(BaseModel):
    response_type: str = "sql"
    sql: str
    columns: List[str]
    data: List[List[Any]]
    row_count: int
    explanation: str
    session_id: str
    query_id: Optional[str] = None


class ChatResponse(BaseModel):
    response_type: str = "chat"
    message: str
    intent_info: Optional[dict] = None
    session_id: str


# Union response type
QueryResponse = SQLQueryResponse | ChatResponse


# ============================================
# ASYNC QUERY PROCESSOR (NON-BLOCKING!)
# ============================================

def _process_query_sync(
    question: str,
    schema_info: str,
    session_id: str,
    selected_tables: List[str]
):
    """
    Synchronous query processing (runs in thread pool)
    Creates NEW provider instances to avoid thread conflicts
    """
    try:
        # CREATE NEW PROVIDERS for this request (thread-safe!)
        current_config = config_manager.get_config()
        llm = ProviderFactory.create_llm_provider(current_config)
        db = ProviderFactory.create_db_provider(current_config)

        print(f"🔄 [Thread {id(llm)}] Processing: {question[:50]}...")

        # Determine intent
        intent_result = llm.determine_intent(question, schema_info)

        # Route based on intent
        if intent_result["intent"] == "sql" and intent_result["confidence"] > 0.6:
            if schema_info == "No schema provided.":
                return {
                    "type": "chat",
                    "message": "☕ Please select one or more tables first.",
                    "intent_info": intent_result
                }

            # Get conversation context
            conversation_context = conversation_manager.get_conversation_context(session_id)

            if len(conversation_context) > 1:
                context_summary = "\n\nRecent conversation:\n"
                for msg in conversation_context[-5:]:
                    if msg['role'] == 'user':
                        context_summary += f"User: {msg['content']}\n"
                    elif msg['role'] == 'assistant':
                        context_summary += f"Assistant: {msg['content'][:100]}...\n"

                enhanced_question = f"{question}\n\nContext: {context_summary}"
            else:
                enhanced_question = question

            # Generate SQL
            sql_query, explanation = llm.generate_sql(enhanced_question, schema_info)

            if not sql_query:
                return {
                    "type": "chat",
                    "message": "Failed to generate SQL. Please rephrase.",
                    "intent_info": intent_result
                }

            # Execute query
            columns, data = db.execute_query(sql_query)

            print(f"✅ [Thread {id(llm)}] Query executed: {len(data)} rows")

            return {
                "type": "sql",
                "sql": sql_query,
                "columns": columns,
                "data": data,
                "row_count": len(data),
                "explanation": explanation,
                "tables": selected_tables
            }

        else:
            # Chat response
            conversation_context = conversation_manager.get_conversation_context(session_id)

            if len(conversation_context) > 1:
                context_text = "Recent conversation:\n"
                for msg in conversation_context[-5:]:
                    role_label = "User" if msg['role'] == 'user' else "Assistant"
                    context_text += f"{role_label}: {msg['content']}\n"

                enhanced_question = f"{context_text}\n\nCurrent: {question}"
            else:
                enhanced_question = question

            chat_response = llm.generate_chat_response(enhanced_question, schema_info)

            return {
                "type": "chat",
                "message": chat_response,
                "intent_info": intent_result
            }

    except Exception as e:
        print(f"❌ [Thread {id(llm) if 'llm' in locals() else 'unknown'}] Error: {e}")
        import traceback
        traceback.print_exc()
        raise


# ============================================
# MAIN ROUTES
# ============================================

@app.get("/", response_class=HTMLResponse)
async def read_root():
    """Serve frontend"""
    frontend_path = os.path.join(PROJECT_ROOT, 'frontend', 'index.html')
    try:
        with open(frontend_path, 'r') as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Frontend not found</h1>", status_code=404)


@app.get("/health")
async def health_check():
    """Health check for all providers"""
    return {
        "status": "healthy",
        "app": config['app']['name'],
        "version": config['app']['version'],
        "llm": {
            "provider": config['llm']['provider'],
            "model": llm_provider.get_model_name(),
            "healthy": llm_provider.health_check()
        },
        "database": {
            "provider": config['database']['provider'],
            "info": db_provider.get_connection_info(),
            "healthy": db_provider.health_check()
        },
        "conversations": conversation_manager.get_stats(),
        "query_history": query_history.get_stats(),
        "thread_pool": {
            "workers": 20,
            "active": MAIN_EXECUTOR._threads.__len__() if hasattr(MAIN_EXECUTOR, '_threads') else 0
        }
    }


@app.get("/config")
async def get_config():
    """Get current configuration (sanitized)"""
    return {
        "llm_provider": config['llm']['provider'],
        "db_provider": config['database']['provider'],
        "llm_model": llm_provider.get_model_name(),
        "db_info": db_provider.get_connection_info()
    }


@app.get("/analytics", response_class=HTMLResponse)
async def analytics_dashboard():
    """Analytics Dashboard"""
    dashboard_path = os.path.join(PROJECT_ROOT, 'frontend', 'analytics_dashboard.html')

    if not os.path.exists(dashboard_path):
        raise HTTPException(status_code=404, detail="Dashboard not found")

    with open(dashboard_path, 'r', encoding='utf-8') as f:
        return f.read()

@app.post("/reload-providers")
async def trigger_reload_providers():
    """Reload providers after configuration change"""
    try:
        reload_providers()

        return {
            "success": True,
            "message": "Providers reloaded successfully",
            "llm_provider": llm_provider.get_model_name(),
            "db_provider": db_provider.get_connection_info()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/tables")
async def list_tables():
    """List available tables (async)"""
    try:
        # Run in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        tables = await loop.run_in_executor(
            MAIN_EXECUTOR,
            db_provider.get_tables
        )
        return {"tables": tables}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.get("/schema/{table_name}")
async def get_schema(table_name: str):
    """Get table schema (async)"""
    try:
        loop = asyncio.get_event_loop()
        schema = await loop.run_in_executor(
            MAIN_EXECUTOR,
            db_provider.get_table_schema,
            table_name
        )
        return {"table": table_name, "schema": schema}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.post("/schema/multiple")
async def get_multiple_schemas(request: dict):
    """Get schemas for multiple tables (async)"""
    try:
        table_names = request.get("tables", [])
        if not table_names:
            raise HTTPException(status_code=400, detail="No tables provided")

        # Process in parallel!
        loop = asyncio.get_event_loop()
        tasks = [
            loop.run_in_executor(
                MAIN_EXECUTOR,
                db_provider.get_table_schema,
                table
            )
            for table in table_names
        ]

        schemas = await asyncio.gather(*tasks)
        combined_schema = "\n\n".join(schemas)

        return {
            "tables": table_names,
            "combined_schema": combined_schema.strip()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.post("/query")
async def process_query(request: QueryRequest):
    """
    ASYNC query processor - NON-BLOCKING!
    Multiple requests can run in parallel
    """
    try:
        start_time = time.time()

        # SESSION MANAGEMENT
        session_id, session = conversation_manager.get_or_create_session(request.session_id)

        # Add user message
        conversation_manager.add_message(
            session_id,
            role="user",
            content=request.question,
            metadata={"table_schema": request.table_schema}
        )

        schema_info = request.table_schema if request.table_schema else "No schema provided."

        # Extract tables
        selected_tables = []
        if schema_info != "No schema provided.":
            for line in schema_info.split('\n'):
                if line.startswith('Table:'):
                    table_name = line.replace('Table:', '').strip()
                    if '.' in table_name:
                        table_name = table_name.split('.')[-1]
                    selected_tables.append(table_name)

        # ASYNC PROCESSING IN THREAD POOL (NON-BLOCKING!)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            MAIN_EXECUTOR,
            _process_query_sync,
            request.question,
            schema_info,
            session_id,
            selected_tables
        )

        execution_time = (time.time() - start_time) * 1000

        # Handle result
        if result["type"] == "sql":
            # Add to history
            history_record = query_history.add_query(
                session_id=session_id,
                question=request.question,
                sql=result["sql"],
                tables=selected_tables,
                row_count=result["row_count"],
                execution_time_ms=execution_time,
                success=True,
                widget_type="default",
                user_id=None
            )

            # Add to conversation
            conversation_manager.add_message(
                session_id,
                role="assistant",
                content=f"SQL: {result['sql']}\n\nExplanation: {result['explanation']}",
                metadata={
                    "response_type": "sql",
                    "row_count": result["row_count"],
                    "columns": result["columns"],
                    "query_id": history_record.id
                }
            )

            return SQLQueryResponse(
                response_type="sql",
                sql=result["sql"],
                columns=result["columns"],
                data=result["data"],
                row_count=result["row_count"],
                explanation=result["explanation"],
                session_id=session_id,
                query_id=history_record.id
            )

        else:  # chat
            conversation_manager.add_message(
                session_id,
                role="assistant",
                content=result["message"],
                metadata={"response_type": "chat"}
            )

            return ChatResponse(
                response_type="chat",
                message=result["message"],
                intent_info=result.get("intent_info"),
                session_id=session_id
            )

    except Exception as e:
        execution_time = (time.time() - start_time) * 1000

        # ← YENİ: Log failed queries to analytics
        query_history.add_query(
            session_id=session_id,
            question=request.question,
            sql="",  # No SQL generated on error
            tables=selected_tables,
            row_count=0,
            execution_time_ms=execution_time,
            success=False,  # ← YENİ
            error_message=str(e),  # ← YENİ
            widget_type="default",  # ← YENİ
            user_id=None  # ← YENİ
        )
        print(f"❌ Query error: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


# ============================================
# CONVERSATION MANAGEMENT ENDPOINTS
# ============================================

@app.get("/conversation/stats")
async def get_conversation_stats():
    """Get conversation manager statistics"""
    return conversation_manager.get_stats()


@app.get("/conversation/history/{session_id}")
async def get_conversation_history(session_id: str):
    """Get conversation history for a session"""
    history = conversation_manager.get_session_history(session_id)

    if not history:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "session_id": session_id,
        "message_count": len(history),
        "messages": history
    }


@app.post("/conversation/clear/{session_id}")
async def clear_conversation(session_id: str):
    """Clear conversation history for a session"""
    conversation_manager.clear_session(session_id)
    return {
        "message": "✅ Conversation cleared",
        "session_id": session_id
    }


@app.delete("/conversation/{session_id}")
async def delete_conversation(session_id: str):
    """Delete a conversation session completely"""
    conversation_manager.delete_session(session_id)
    return {
        "message": "✅ Session deleted",
        "session_id": session_id
    }


@app.post("/conversation/cleanup")
async def cleanup_expired_conversations():
    """Manually trigger cleanup of expired sessions"""
    cleaned = conversation_manager.cleanup_expired_sessions()
    return {
        "message": f"✅ Cleaned up {cleaned} expired sessions",
        "cleaned_count": cleaned
    }


# ============================================
# QUERY HISTORY ENDPOINTS
# ============================================

@app.get("/history")
async def get_query_history(
    session_id: str,
    limit: int = 20,
    offset: int = 0,
    search: Optional[str] = None
):
    """Get query history for a session"""
    history = query_history.get_history(
        session_id=session_id,
        limit=limit,
        offset=offset,
        search=search
    )

    return {
        "session_id": session_id,
        "count": len(history),
        "queries": history
    }


@app.delete("/history/{query_id}")
async def delete_from_history(query_id: str, session_id: str):
    """Delete a query from history"""
    success = query_history.delete_query(query_id, session_id)

    if not success:
        raise HTTPException(status_code=404, detail="Query not found")

    return {
        "message": "✅ Query deleted from history",
        "query_id": query_id
    }


@app.post("/history/clear/{session_id}")
async def clear_query_history(session_id: str):
    """Clear all history for a session (keeps favorites)"""
    removed = query_history.clear_history(session_id)

    return {
        "message": f"✅ Cleared {removed} queries from history",
        "session_id": session_id,
        "removed_count": removed
    }


# ============================================
# FAVORITES ENDPOINTS
# ============================================

class FavoriteRequest(BaseModel):
    query_id: Optional[str] = None
    question: Optional[str] = None
    sql: Optional[str] = None
    tables: Optional[List[str]] = None
    favorite_name: Optional[str] = None
    tags: Optional[List[str]] = None


@app.get("/favorites")
async def get_favorites(
    limit: int = 50,
    search: Optional[str] = None
):
    """Get all favorites"""
    favorites = query_history.get_favorites(
        limit=limit,
        search=search
    )

    return {
        "count": len(favorites),
        "favorites": favorites
    }


@app.post("/favorites")
async def add_favorite(request: FavoriteRequest, session_id: Optional[str] = None):
    """Add a query to favorites"""
    record = query_history.add_to_favorites(
        query_id=request.query_id,
        session_id=session_id,
        question=request.question,
        sql=request.sql,
        tables=request.tables,
        favorite_name=request.favorite_name,
        tags=request.tags
    )

    if not record:
        raise HTTPException(
            status_code=400,
            detail="Could not add favorite. Provide either query_id or question+sql"
        )

    return {
        "message": "✅ Added to favorites",
        "favorite": record.to_dict()
    }


@app.delete("/favorites/{query_id}")
async def remove_favorite(query_id: str):
    """Remove a query from favorites"""
    success = query_history.remove_from_favorites(query_id)

    if not success:
        raise HTTPException(status_code=404, detail="Favorite not found")

    return {
        "message": "✅ Removed from favorites",
        "query_id": query_id
    }


@app.get("/history/stats")
async def get_history_stats():
    """Get query history statistics"""
    return query_history.get_stats()


# ============================================
# SHUTDOWN
# ============================================

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    print("\n Shutting down SQLatte...")
    MAIN_EXECUTOR.shutdown(wait=True)
    print("✅ Thread pool closed")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=config['app']['host'],
        port=config['app']['port'],
        log_level="info"
    )