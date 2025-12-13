from fastapi import FastAPI, HTTPException
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
    description="☕ Serving perfect SQL queries, freshly brewed"
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

class SQLQueryResponse(BaseModel):
    response_type: str = "sql"
    sql: str
    columns: List[str]
    data: List[List[Any]]
    row_count: int
    explanation: str

class ChatResponse(BaseModel):
    response_type: str = "chat"
    message: str
    intent_info: Optional[dict] = None

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
    Intelligent query processor - handles both SQL and chat
    
    Flow:
    1. Determine intent (SQL or chat)
    2. If SQL → generate & execute query
    3. If chat → generate conversational response
    """
    try:
        schema_info = request.table_schema
        
        if not schema_info:
            schema_info = "No schema provided."
        
        # Step 1: Determine intent
        intent_result = llm_provider.determine_intent(
            request.question,
            schema_info
        )
        
        # Step 2: Route based on intent
        if intent_result["intent"] == "sql" and intent_result["confidence"] > 0.6:
            # SQL Query path
            if schema_info == "No schema provided.":
                # User wants SQL but no tables selected
                return ChatResponse(
                    response_type="chat",
                    message="☕ I'd love to help you query your data! But first, please select one or more tables from the dropdown above so I know what data we're working with.",
                    intent_info=intent_result
                )
            
            # Generate SQL
            sql_query, explanation = llm_provider.generate_sql(
                request.question,
                schema_info
            )
            
            if not sql_query:
                raise HTTPException(status_code=400, detail="Failed to generate SQL")
            
            # Execute query
            columns, data = db_provider.execute_query(sql_query)
            
            return SQLQueryResponse(
                response_type="sql",
                sql=sql_query,
                columns=columns,
                data=data,
                row_count=len(data),
                explanation=explanation
            )
        
        else:
            # Chat path
            chat_response = llm_provider.generate_chat_response(
                request.question,
                schema_info
            )
            
            return ChatResponse(
                response_type="chat",
                message=chat_response,
                intent_info=intent_result
            )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app, 
        host=config['app']['host'], 
        port=config['app']['port'],
        log_level="info"
    )
