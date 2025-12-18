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
    description="☕ Serving perfect SQL queries with conversation memory"
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


# Request/Response Models
class QueryRequest(BaseModel):
    question: str
    table_schema: str = ""
    session_id: Optional[str] = None  # NEW: Session tracking


class SQLQueryResponse(BaseModel):
    response_type: str = "sql"
    sql: str
    columns: List[str]
    data: List[List[Any]]
    row_count: int
    explanation: str
    session_id: str  # NEW: Return session ID


class ChatResponse(BaseModel):
    response_type: str = "chat"
    message: str
    intent_info: Optional[dict] = None
    session_id: str  # NEW: Return session ID


# Union response type
QueryResponse = SQLQueryResponse | ChatResponse


# Routes
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
        "conversations": conversation_manager.get_stats()  # NEW: Conversation stats
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
    Intelligent query processor with CONVERSATION MEMORY

    Flow:
    1. Get or create session
    2. Add user message to conversation history
    3. Get conversation context for LLM
    4. Determine intent (SQL or chat)
    5. Process query with context
    6. Add assistant response to conversation history
    """
    try:
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

        # ============================================
        # DETERMINE INTENT (with conversation context)
        # ============================================
        intent_result = llm_provider.determine_intent(
            request.question,
            schema_info
        )

        # ============================================
        # ROUTE BASED ON INTENT
        # ============================================
        if intent_result["intent"] == "sql" and intent_result["confidence"] > 0.6:
            # SQL Query path
            if schema_info == "No schema provided.":
                # User wants SQL but no tables selected
                response_message = "☕ I'd love to help you query your data! But first, please select one or more tables from the dropdown above so I know what data we're working with."

                # Add assistant response to conversation
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
            # Get recent conversation for context
            conversation_context = conversation_manager.get_conversation_context(session_id)

            # Build enhanced prompt with conversation history
            if len(conversation_context) > 1:  # If there's history
                context_summary = "\n\nRecent conversation:\n"
                for msg in conversation_context[-5:]:  # Last 5 messages
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

            # Add assistant response to conversation
            conversation_manager.add_message(
                session_id,
                role="assistant",
                content=f"SQL Query: {sql_query}\n\nExplanation: {explanation}",
                metadata={
                    "response_type": "sql",
                    "row_count": len(data),
                    "columns": columns
                }
            )

            return SQLQueryResponse(
                response_type="sql",
                sql=sql_query,
                columns=columns,
                data=data,
                row_count=len(data),
                explanation=explanation,
                session_id=session_id
            )

        else:
            # ============================================
            # CHAT PATH WITH CONVERSATION MEMORY
            # ============================================
            # Get conversation context
            conversation_context = conversation_manager.get_conversation_context(session_id)

            # Enhanced chat prompt with conversation history
            if len(conversation_context) > 1:
                # Build conversation context for LLM
                context_text = "Recent conversation:\n"
                for msg in conversation_context[-5:]:
                    role_label = "User" if msg['role'] == 'user' else "You (Assistant)"
                    context_text += f"{role_label}: {msg['content']}\n"

                enhanced_question = f"{context_text}\n\nUser's current question: {request.question}\n\nProvide a helpful response that takes into account the conversation history."
            else:
                enhanced_question = request.question

            # Generate chat response
            chat_response = llm_provider.generate_chat_response(
                enhanced_question,
                schema_info
            )

            # Add assistant response to conversation
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
# CONVERSATION MANAGEMENT ENDPOINTS (NEW!)
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=config['app']['host'],
        port=config['app']['port'],
        log_level="info"
    )