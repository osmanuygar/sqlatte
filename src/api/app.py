"""
SQLatte API - Enhanced with Query History & Favorites + Admin Configuration
"""

import time
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

# Load configuration from file
CONFIG_PATH = os.path.join(PROJECT_ROOT, 'config', 'config.yaml')
config = config_manager.load_from_file(CONFIG_PATH)

# Create providers
llm_provider = ProviderFactory.create_llm_provider(config)
db_provider = ProviderFactory.create_db_provider(config)

# ============================================
# DYNAMIC PROVIDER RELOAD
# ============================================
def reload_providers():
    """
    Reload providers with current configuration
    Call this after config updates to apply changes
    """
    global llm_provider, db_provider

    current_config = config_manager.get_config()

    try:
        # Recreate LLM provider
        llm_provider = ProviderFactory.create_llm_provider(current_config)
        print("✅ LLM provider reloaded")
    except Exception as e:
        print(f"⚠️ Failed to reload LLM provider: {e}")

    try:
        # Recreate Database provider
        db_provider = ProviderFactory.create_db_provider(current_config)
        print("✅ Database provider reloaded")
    except Exception as e:
        print(f"⚠️ Failed to reload Database provider: {e}")


# Initialize FastAPI
app = FastAPI(
    title=config['app']['name'],
    version=config['app']['version'],
    description="☕ Serving perfect SQL queries with conversation memory, query history & runtime configuration"
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

# Include admin routes
app.include_router(admin_router)


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
        "query_history": query_history.get_stats()
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


@app.post("/reload-providers")
async def trigger_reload_providers():
    """
    Reload providers after configuration change

    ⚠️ Call this endpoint after updating config via /admin
    """
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
    """List available tables"""
    try:
        tables = db_provider.get_tables()
        return {"tables": tables}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.get("/schema/{table_name}")
async def get_schema(table_name: str):
    """Get table schema"""
    try:
        schema = db_provider.get_table_schema(table_name)
        return {"table": table_name, "schema": schema}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.post("/schema/multiple")
async def get_multiple_schemas(request: dict):
    """Get schemas for multiple tables (for JOINs)"""
    try:
        table_names = request.get("tables", [])
        if not table_names:
            raise HTTPException(status_code=400, detail="No tables provided")

        combined_schema = ""
        for table in table_names:
            schema = db_provider.get_table_schema(table)
            combined_schema += schema + "\n\n"

        return {
            "tables": table_names,
            "combined_schema": combined_schema.strip()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.post("/query")
async def process_query(request: QueryRequest):
    """
    Intelligent query processor with CONVERSATION MEMORY & QUERY HISTORY
    """
    try:
        start_time = time.time()

        # SESSION MANAGEMENT
        session_id, session = conversation_manager.get_or_create_session(request.session_id)

        # Add user message to conversation history
        conversation_manager.add_message(
            session_id,
            role="user",
            content=request.question,
            metadata={"table_schema": request.table_schema}
        )

        schema_info = request.table_schema
        if not schema_info:
            schema_info = "No schema provided."

        # Extract tables from schema
        selected_tables = []
        if schema_info != "No schema provided.":
            for line in schema_info.split('\n'):
                if line.startswith('Table:'):
                    table_name = line.replace('Table:', '').strip()
                    if '.' in table_name:
                        table_name = table_name.split('.')[-1]
                    selected_tables.append(table_name)

        # DETERMINE INTENT
        intent_result = llm_provider.determine_intent(
            request.question,
            schema_info
        )

        # ROUTE BASED ON INTENT
        if intent_result["intent"] == "sql" and intent_result["confidence"] > 0.6:
            if schema_info == "No schema provided.":
                response_message = "☕ I'd love to help you query your data! But first, please select one or more tables from the dropdown above so I know what data we're working with."

                conversation_manager.add_message(
                    session_id,
                    role="assistant",
                    content=response_message,
                    metadata={"response_type": "chat"}
                )

                return ChatResponse(
                    response_type="chat",
                    message=response_message,
                    intent_info=intent_result,
                    session_id=session_id
                )

            # GENERATE SQL WITH CONVERSATION CONTEXT
            conversation_context = conversation_manager.get_conversation_context(session_id)

            if len(conversation_context) > 1:
                context_summary = "\n\nRecent conversation:\n"
                for msg in conversation_context[-5:]:
                    if msg['role'] == 'user':
                        context_summary += f"User: {msg['content']}\n"
                    elif msg['role'] == 'assistant':
                        context_summary += f"Assistant: {msg['content'][:100]}...\n"

                enhanced_question = f"{request.question}\n\nContext: User is continuing a conversation. {context_summary}"
            else:
                enhanced_question = request.question

            # Generate SQL
            sql_query, explanation = llm_provider.generate_sql(
                enhanced_question,
                schema_info
            )

            if not sql_query:
                raise HTTPException(status_code=400, detail="Failed to generate SQL")

            # Execute query
            columns, data = db_provider.execute_query(sql_query)

            execution_time = (time.time() - start_time) * 1000  # ms

            # ADD TO QUERY HISTORY
            history_record = query_history.add_query(
                session_id=session_id,
                question=request.question,
                sql=sql_query,
                tables=selected_tables,
                row_count=len(data),
                execution_time_ms=execution_time
            )

            # Add assistant response to conversation
            conversation_manager.add_message(
                session_id,
                role="assistant",
                content=f"SQL Query: {sql_query}\n\nExplanation: {explanation}",
                metadata={
                    "response_type": "sql",
                    "row_count": len(data),
                    "columns": columns,
                    "query_id": history_record.id
                }
            )

            return SQLQueryResponse(
                response_type="sql",
                sql=sql_query,
                columns=columns,
                data=data,
                row_count=len(data),
                explanation=explanation,
                session_id=session_id,
                query_id=history_record.id
            )

        else:
            # CHAT PATH WITH CONVERSATION MEMORY
            conversation_context = conversation_manager.get_conversation_context(session_id)

            if len(conversation_context) > 1:
                context_text = "Recent conversation:\n"
                for msg in conversation_context[-5:]:
                    role_label = "User" if msg['role'] == 'user' else "You (Assistant)"
                    context_text += f"{role_label}: {msg['content']}\n"

                enhanced_question = f"{context_text}\n\nUser's current question: {request.question}\n\nProvide a helpful response that takes into account the conversation history."
            else:
                enhanced_question = request.question

            chat_response = llm_provider.generate_chat_response(
                enhanced_question,
                schema_info
            )

            conversation_manager.add_message(
                session_id,
                role="assistant",
                content=chat_response,
                metadata={"response_type": "chat"}
            )

            return ChatResponse(
                response_type="chat",
                message=chat_response,
                intent_info=intent_result,
                session_id=session_id
            )

    except Exception as e:
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=config['app']['host'],
        port=config['app']['port'],
        log_level="info"
    )