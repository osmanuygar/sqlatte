"""
SQLatte API - Enhanced with Query History & Favorites
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
from src.core.config_loader import ConfigLoader
from src.core.provider_factory import ProviderFactory
from src.core.conversation_manager import conversation_manager
from src.core.query_history import query_history

# Load configuration
CONFIG_PATH = os.path.join(PROJECT_ROOT, 'config', 'config.yaml')
config = ConfigLoader.load(CONFIG_PATH)

# Create providers
llm_provider = ProviderFactory.create_llm_provider(config)
db_provider = ProviderFactory.create_db_provider(config)

# Initialize FastAPI
app = FastAPI(
    title=config['app']['name'],
    version=config['app']['version'],
    description="☕ Serving perfect SQL queries with conversation memory & query history"
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
    query_id: Optional[str] = None  # NEW: For history tracking


class ChatResponse(BaseModel):
    response_type: str = "chat"
    message: str
    intent_info: Optional[dict] = None
    session_id: str


# NEW: History & Favorites Models
class FavoriteRequest(BaseModel):
    query_id: Optional[str] = None  # Mark existing query as favorite
    question: Optional[str] = None  # Or create new favorite
    sql: Optional[str] = None
    tables: Optional[List[str]] = None
    favorite_name: Optional[str] = None
    tags: Optional[List[str]] = None


class HistorySearchRequest(BaseModel):
    search: Optional[str] = None
    tables_filter: Optional[List[str]] = None
    limit: int = 20
    offset: int = 0


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
        "query_history": query_history.get_stats()  # NEW
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

        # ============================================
        # SESSION MANAGEMENT
        # ============================================
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

        # Extract tables from schema (simple parsing)
        selected_tables = []
        if schema_info != "No schema provided.":
            for line in schema_info.split('\n'):
                if line.startswith('Table:'):
                    table_name = line.replace('Table:', '').strip()
                    if '.' in table_name:
                        table_name = table_name.split('.')[-1]
                    selected_tables.append(table_name)

        # ============================================
        # DETERMINE INTENT
        # ============================================
        intent_result = llm_provider.determine_intent(
            request.question,
            schema_info
        )

        # ============================================
        # ROUTE BASED ON INTENT
        # ============================================
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

            # ============================================
            # GENERATE SQL WITH CONVERSATION CONTEXT
            # ============================================
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

            # ============================================
            # ADD TO QUERY HISTORY (NEW!)
            # ============================================
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
                query_id=history_record.id  # NEW: Return query ID
            )

        else:
            # ============================================
            # CHAT PATH WITH CONVERSATION MEMORY
            # ============================================
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
# QUERY HISTORY ENDPOINTS (NEW!)
# ============================================

@app.get("/history")
async def get_query_history(
    session_id: str,
    limit: int = 20,
    offset: int = 0,
    search: Optional[str] = None
):
    """
    Get query history for a session

    Args:
        session_id: User session ID
        limit: Max results (default 20)
        offset: Pagination offset
        search: Optional search term
    """
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


@app.post("/history/search")
async def search_query_history(request: HistorySearchRequest, session_id: str):
    """Advanced history search with filters"""
    history = query_history.get_history(
        session_id=session_id,
        limit=request.limit,
        offset=request.offset,
        search=request.search,
        tables_filter=request.tables_filter
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
# FAVORITES ENDPOINTS (NEW!)
# ============================================

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
    """
    Add a query to favorites

    Can either:
    1. Mark existing query as favorite (provide query_id)
    2. Create new favorite (provide question + sql)
    """
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


@app.get("/favorites/{query_id}")
async def get_favorite(query_id: str):
    """Get a specific favorite query"""
    query = query_history.get_query_by_id(query_id)

    if not query:
        raise HTTPException(status_code=404, detail="Query not found")

    return query


# ============================================
# SUGGESTIONS ENDPOINT (NEW!)
# ============================================

@app.get("/suggestions")
async def get_suggestions(
    session_id: str,
    tables: str  # Comma-separated table names
):
    """
    Get query suggestions based on current context

    Args:
        session_id: User session
        tables: Currently selected tables (comma-separated)
    """
    table_list = [t.strip() for t in tables.split(',') if t.strip()]

    suggestions = query_history.get_suggested_queries(
        session_id=session_id,
        current_tables=table_list,
        limit=5
    )

    recent_tables = query_history.get_recent_tables(session_id, limit=5)

    return {
        "suggestions": suggestions,
        "recent_tables": recent_tables
    }


# ============================================
# HISTORY STATS ENDPOINT (NEW!)
# ============================================

@app.get("/history/stats")
async def get_history_stats():
    """Get query history statistics"""
    return query_history.get_stats()


@app.post("/history/cleanup")
async def cleanup_old_history():
    """Manually trigger cleanup of old history"""
    removed = query_history.cleanup_old_history()

    return {
        "message": f"✅ Cleaned up {removed} old history entries",
        "removed_count": removed
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=config['app']['host'],
        port=config['app']['port'],
        log_level="info"
    )