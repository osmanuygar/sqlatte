"""
SQLatte API - Optimized with Async Processing & Thread Pool
"""

import time
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Any, Optional, Dict
import os
import sys

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Now import from src
#from src.core.config_manager import config_manager
from src.core.provider_factory import ProviderFactory
from src.core.config_manager_enhanced import config_manager
from src.core.conversation_manager import conversation_manager
from src.core.query_history import query_history
from src.api.admin_routes_enhanced import router as admin_router
from src.api.demo_routes import router as demo_router
from src.api.analytics_routes import router as analytics_router
from src.core.analytics_db_postgres import analytics_db
from src.core.audit_log_db import audit_log_db
from src.api.audit_routes import router as audit_router
from src.api.dashboard_routes import router as dashboard_router
from src.core.dashboard_manager import initialize_dashboard_manager
from src.api.semantic_routes import router as semantic_router
from src.api import ops_agent_routes
from src.core.provider_factory import initialize_ops_agent
from src.api import alarm_routes
from src.core.alarm_service import initialize_alarm_service, get_alarm_service
from src.api import file_analysis_routes

#from src.core.simple_insights import simple_insights
from src.core.llm_insights_engine import (
    initialize_insights_engine,
    get_insights_engine
)

# Setup logging
logger = logging.getLogger(__name__)

# Scheduled Queries
from src.core.scheduled_queries_db import ScheduledQueriesDB, ScheduledQueriesDBPostgres
from src.core.scheduler_manager import SchedulerManager
from src.core.email_service import EmailService, MockEmailService
from src.api import scheduled_routes



# Plugin system
from src.plugins.base_plugin import plugin_manager
from src.plugins.auth_plugin import create_auth_plugin

# Load configuration from file
CONFIG_PATH = os.path.join(PROJECT_ROOT, 'config', 'config.yaml')
config = config_manager.load_from_file(CONFIG_PATH, enable_db=True)

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

initialize_ops_agent(config)
# Initialize providers
llm_provider, db_provider = get_current_providers()

# Scheduled Queries components (initialized in startup)
schedules_db = None
scheduler_manager = None
email_service = None

print(f"✅ Initial providers loaded:")
print(f"   LLM: {llm_provider.get_model_name()}")
print(f"   DB: {db_provider.get_connection_info()['type']}")
print(f"📅 Scheduled queries will be initialized on startup")

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
app.include_router(scheduled_routes.router)
app.include_router(dashboard_router)
app.include_router(semantic_router)
app.include_router(ops_agent_routes.router)
app.include_router(alarm_routes.router)
app.include_router(audit_router)
app.include_router(file_analysis_routes.router)
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
    insights: Optional[List[Dict]] = None


class ChatResponse(BaseModel):
    response_type: str = "chat"
    message: str
    intent_info: Optional[dict] = None
    session_id: str


class SecurityWarningResponse(BaseModel):
    response_type: str = "warning"
    message: str
    sql: str
    reason: str
    session_id: str


# Union response type
QueryResponse = SQLQueryResponse | ChatResponse | SecurityWarningResponse


# ============================================
# ASYNC QUERY PROCESSOR (NON-BLOCKING!)
# ============================================
def _process_query_sync(
    question: str,
    schema_info: str,
    session_id: str,
    selected_tables: list
):
    """
    Synchronous query processing (runs in thread pool).
    Her task için ayrı LLM provider oluşturur → farklı model kullanımı.
    """
    try:
        current_config = config_manager.get_config()

        # ── Task-based LLM providers ─────────────────────────────────────
        # Her biri config.yaml'daki model_routing'e göre farklı model kullanır.
        # create_llm_provider_for_task() → routing yoksa default model'e fallback.
        llm_intent   = ProviderFactory.create_llm_provider_for_task(current_config, "intent_detection")
        llm_sql      = ProviderFactory.create_llm_provider_for_task(current_config, "sql")
        llm_chat     = ProviderFactory.create_llm_provider_for_task(current_config, "chat")
        llm_insights = ProviderFactory.create_llm_provider_for_task(current_config, "insights")

        # Database provider (değişmedi)
        db = ProviderFactory.create_db_provider(current_config)

        print(f"🔄 [ModelRouting] intent={llm_intent.get_model_name()} | "
              f"sql={llm_sql.get_model_name()} | "
              f"chat={llm_chat.get_model_name()} | "
              f"insights={llm_insights.get_model_name()}")

        print(f"🔄 Processing: {question[:60]}...")

        # ── Intent Detection (hızlı/ucuz model) ─────────────────────────
        intent_result = llm_intent.determine_intent(question, schema_info)
        if audit_log_db:
            _u = getattr(llm_intent, "last_token_usage", {})
            audit_log_db.log(
                session_id=session_id, operation_type="intent_detection",
                model_name=llm_intent.get_model_name(), question=question,
                prompt_preview=question[:500],
                input_tokens=_u.get("input_tokens", 0),
                output_tokens=_u.get("output_tokens", 0),
            )

        # ── SQL path ─────────────────────────────────────────────────────
        if intent_result["intent"] == "sql" and intent_result["confidence"] > 0.6:

            if schema_info == "No schema provided.":
                return {
                    "type": "chat",
                    "message": "☕ Please select one or more tables first.",
                    "intent_info": intent_result
                }

            # Conversation context
            conversation_context = conversation_manager.get_conversation_context(session_id)
            if len(conversation_context) > 1:
                context_summary = "\n\nRecent conversation:\n"
                for msg in conversation_context[-5:]:
                    role_label = "User" if msg['role'] == 'user' else "Assistant"
                    context_summary += f"{role_label}: {msg['content'][:100]}\n"
                enhanced_question = f"{question}\n\nContext: {context_summary}"
            else:
                enhanced_question = question

            # SQL generation (güçlü model)
            sql_query, explanation = llm_sql.generate_sql(enhanced_question, schema_info)
            if audit_log_db:
                _u = getattr(llm_sql, "last_token_usage", {})
                audit_log_db.log(
                    session_id=session_id, operation_type="sql_generation",
                    model_name=llm_sql.get_model_name(), question=question,
                    prompt_preview=enhanced_question[:500],
                    input_tokens=_u.get("input_tokens", 0),
                    output_tokens=_u.get("output_tokens", 0),
                )

            if not sql_query:
                return {
                    "type": "chat",
                    "message": "Failed to generate SQL. Please rephrase.",
                    "intent_info": intent_result
                }

            # Block non-SELECT queries (SQL injection prevention)
            from src.core.sql_validator import is_select_only, violation_reason
            if not is_select_only(sql_query):
                reason = violation_reason(sql_query)
                print(f"🚫 Blocked non-SELECT query: {reason} | SQL: {sql_query[:120]}")
                return {
                    "type": "security_warning",
                    "sql": sql_query,
                    "reason": reason,
                    "message": f"Only SELECT queries are permitted. {reason}.",
                }

            # Execute query
            columns, data = db.execute_query(sql_query)
            print(f"✅ Query executed: {len(data)} rows")

            # Insights (güçlü model — insights engine config'den okur)
            insights = []
            try:
                engine = get_insights_engine()
                if engine is None:
                    print("⚠️ Insights engine not initialized")
                else:
                    # Insights engine kendi LLM'ini oluşturuyor,
                    # model_routing'deki "insights" modelini config'den alır.
                    insights = engine.generate_insights(
                        columns=columns,
                        data=data,
                        user_question=question,
                        schema_info=schema_info,
                        sql_query=sql_query
                    )
                    if insights:
                        print(f"🧠 Generated {len(insights)} insights")
            except Exception as e:
                print(f"⚠️ Insights generation failed: {e}")
                import traceback
                traceback.print_exc()

            return {
                "type": "sql",
                "sql": sql_query,
                "columns": columns,
                "data": data,
                "row_count": len(data),
                "explanation": explanation,
                "insights": insights,
                "tables": selected_tables
            }

        # ── Chat path (hızlı/orta model) ────────────────────────────────
        else:
            conversation_context = conversation_manager.get_conversation_context(session_id)

            if len(conversation_context) > 1:
                context_text = "Recent conversation:\n"
                for msg in conversation_context[-5:]:
                    role_label = "User" if msg['role'] == 'user' else "Assistant"
                    context_text += f"{role_label}: {msg['content']}\n"
                enhanced_question = f"{context_text}\n\nCurrent: {question}"
            else:
                enhanced_question = question

            # Chat response (chat modeli)
            chat_response = llm_chat.generate_chat_response(enhanced_question, schema_info)
            if audit_log_db:
                _u = getattr(llm_chat, "last_token_usage", {})
                audit_log_db.log(
                    session_id=session_id, operation_type="chat_response",
                    model_name=llm_chat.get_model_name(), question=question,
                    prompt_preview=enhanced_question[:500],
                    input_tokens=_u.get("input_tokens", 0),
                    output_tokens=_u.get("output_tokens", 0),
                )

            return {
                "type": "chat",
                "message": chat_response,
                "intent_info": intent_result
            }

    except Exception as e:
        print(f"❌ Query processing error: {e}")
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


@app.get("/scheduler-admin.html", response_class=HTMLResponse)
async def scheduler_admin_page():
    """Serve scheduler admin page"""
    admin_path = os.path.join(PROJECT_ROOT, 'frontend', 'scheduler-admin.html')
    try:
        with open(admin_path, 'r', encoding='utf-8') as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Scheduler Admin not found</h1>", status_code=404)


@app.get("/admin.html", response_class=HTMLResponse)
async def config_admin_page():
    """Serve config admin page"""
    admin_path = os.path.join(PROJECT_ROOT, 'frontend', 'admin.html')
    try:
        with open(admin_path, 'r', encoding='utf-8') as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Config Admin not found</h1>", status_code=404)


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
        "insights_engine": "active",
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


@app.get("/ui-config")
async def get_ui_config():
    """
    Return which sidebar sections are enabled.

    Maps config.yaml ui.sections keys to HTML section IDs:
      bigquery_ops  →  bigquery-ops

    'home' is always enabled and not included in the map.
    """
    # Key: section id used in HTML, Value: enabled bool
    DEFAULTS = {
        "assistant":     True,
        "demo":          True,
        "analytics":     True,
        "schedules":     True,
        "dashboards":    True,
        "bigquery-ops":  True,
        "admin":         True,
        "file-analyzer": True,
    }

    raw = config.get("ui", {}).get("sections", {})

    # Normalise underscore keys (bigquery_ops) to hyphen (bigquery-ops)
    normalised = {k.replace("_", "-"): v for k, v in raw.items()}

    sections = {
        section_id: normalised.get(section_id, default)
        for section_id, default in DEFAULTS.items()
    }

    return {"sections": sections}


@app.get("/analytics", response_class=HTMLResponse)
async def analytics_dashboard():
    """Analytics Dashboard"""
    if analytics_db is None:
        return HTMLResponse(
            content="""
                <!DOCTYPE html>
                <html>
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <title>Analytics Disabled - SQLatte</title>
                    <style>
                        body {
                            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                            background: linear-gradient(135deg, #3e2c23 0%, #1f140f 100%);
                            color: #f5f1ea;
                            padding: 40px;
                            text-align: center;
                            min-height: 100vh;
                            display: flex;
                            align-items: center;
                            justify-content: center;
                        }
                        
                        .container {
                            max-width: 800px;
                            background: #2b1d17;
                            padding: 40px;
                            border-radius: 12px;
                            border: 1px solid #4a332a;
                            box-shadow: 0 10px 30px rgba(0,0,0,0.4);
                        }
                        
                        h1 {
                            font-size: 32px;
                            margin-bottom: 20px;
                            background: linear-gradient(135deg, #c69c6d 0%, #8b5e3c 100%);
                            -webkit-background-clip: text;
                            -webkit-text-fill-color: transparent;
                        }
                        
                        p { 
                            color: #cbb8a6; 
                            margin: 15px 0; 
                        }
                        
                        pre {
                            background: #1b120d;
                            padding: 20px;
                            border-radius: 8px;
                            text-align: left;
                            overflow-x: auto;
                            border: 1px solid #3d2a21;
                            color: #e6c7a1;
                        }
                        
                        a {
                            color: #d7a86e;
                            text-decoration: none;
                            margin-top: 20px;
                            display: inline-block;
                        }
                        
                        a:hover { 
                            text-decoration: underline; 
                            color: #f0c48a;
                        }
                        
                        .steps {
                            text-align: left;
                            margin: 30px 0;
                            padding: 20px;
                            background: #1b120d;
                            border-radius: 8px;
                            border: 1px solid #3d2a21;
                        }
                        
                        .steps ol { 
                            margin: 10px 0; 
                            padding-left: 25px; 
                        }
                        
                        .steps li { 
                            margin: 10px 0; 
                            color: #f5f1ea; 
                        }
                        </style>
                </head>
                <body>
                    <div class="container">
                        <h1>📊 Analytics Dashboard</h1>
                        <p style="font-size: 18px; color: #D4A574;">Analytics is currently disabled.</p>

                        <div class="steps">
                            <p><strong>To enable analytics, follow these steps:</strong></p>
                            <ol>
                                <li>Install PostgreSQL (if not already installed)</li>
                                <li>Create database and user:
                                    <pre style="margin-top: 10px;">sudo -u postgres psql
    CREATE DATABASE sqllatte_analytics;
    CREATE USER sqllatte WITH PASSWORD 'your_password';
    GRANT ALL PRIVILEGES ON DATABASE sqllatte_analytics TO sqllatte;
    \\c sqllatte_analytics
    GRANT ALL ON SCHEMA public TO sqllatte;</pre>
                                </li>
                                <li>Update <code>config/config.yaml</code>:
                                    <pre style="margin-top: 10px;">analytics:
      enabled: true
      backend: "postgresql"
      postgresql:
        host: "localhost"
        port: 5432
        database: "sqllatte_analytics"
        user: "sqllatte"
        password: "your_password"</pre>
                                </li>
                                <li>Restart the server: <code>python run.py</code></li>
                            </ol>
                        </div>

                        <p><a href="/">← Back to Home</a></p>
                    </div>
                </body>
                </html>
                """,
            status_code=200
        )
    dashboard_path = os.path.join(PROJECT_ROOT, 'frontend', 'analytics_dashboard.html')

    if not os.path.exists(dashboard_path):
        raise HTTPException(status_code=404, detail="Dashboard not found")

    with open(dashboard_path, 'r', encoding='utf-8') as f:
        return f.read()


@app.get("/admin/schedules", response_class=HTMLResponse)
async def schedules_admin_page():
    """
    Schedule Management Admin Page - Unified scheduler admin
    Shows system status, schedules, and jobs in tabbed interface
    """
    scheduler_admin_path = os.path.join(PROJECT_ROOT, 'frontend', 'scheduler-admin.html')

    if not os.path.exists(scheduler_admin_path):
        # Fallback: Return simple error page
        return HTMLResponse(
            content="""
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Scheduler Admin - Not Found</title>
                    <style>
                        body {
                            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                            background: #0f0f0f;
                            color: #e0e0e0;
                            display: flex;
                            align-items: center;
                            justify-content: center;
                            height: 100vh;
                            margin: 0;
                        }
                        .error-container {
                            text-align: center;
                            padding: 40px;
                            background: #1a1a1a;
                            border-radius: 12px;
                            border: 1px solid #333;
                        }
                        h1 { color: #D4A574; margin-bottom: 20px; }
                        p { color: #a0a0a0; margin-bottom: 20px; }
                        a { 
                            color: #D4A574; 
                            text-decoration: none; 
                            padding: 10px 20px;
                            background: rgba(212, 165, 116, 0.1);
                            border-radius: 8px;
                            display: inline-block;
                        }
                        a:hover { background: rgba(212, 165, 116, 0.2); }
                    </style>
                </head>
                <body>
                    <div class="error-container">
                        <h1>⏰ Scheduler Admin Page Not Found</h1>
                        <p>The scheduler-admin.html file is missing from the frontend directory.</p>
                        <p><code>frontend/scheduler-admin.html</code></p>
                        <a href="/">← Back to Home</a>
                    </div>
                </body>
                </html>
            """,
            status_code=404
        )

    with open(scheduler_admin_path, 'r', encoding='utf-8') as f:
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
                query_id=history_record.id,
                insights=result.get("insights", [])
            )

        elif result["type"] == "security_warning":
            conversation_manager.add_message(
                session_id,
                role="assistant",
                content=f"[Security Warning] {result['reason']}",
                metadata={"response_type": "warning"}
            )
            return SecurityWarningResponse(
                response_type="warning",
                message=result["message"],
                sql=result["sql"],
                reason=result["reason"],
                session_id=session_id,
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
async def remove_favorite(query_id: str, force: bool = False):
    """
    Remove a query from favorites

    Args:
        query_id: Query ID to remove
        force: If true, delete even if schedules exist (cascade delete)
    """
    # Check if there are schedules using this query
    if schedules_db and scheduler_manager:
        # Get all schedules for this query
        all_schedules = await schedules_db.get_all_enabled_schedules()
        related_schedules = [s for s in all_schedules if s.get('query_id') == query_id]

        if related_schedules and not force:
            # Warning: schedules exist
            return {
                "error": "scheduled_queries_exist",
                "message": f"⚠️ This query has {len(related_schedules)} active schedule(s). Delete schedules first or use force=true",
                "schedules": [
                    {
                        "id": s['id'],
                        "name": s['name'],
                        "frequency": s['frequency']
                    }
                    for s in related_schedules
                ],
                "query_id": query_id
            }

        # Force delete or no schedules - cascade delete schedules
        if related_schedules and force:
            logger.info(f"🗑️ Cascade deleting {len(related_schedules)} schedules for query {query_id}")

            for schedule in related_schedules:
                try:
                    # Remove from scheduler
                    scheduler_manager.remove_job(schedule['id'])

                    # Delete from database
                    await schedules_db.delete_schedule(schedule['id'])

                    logger.info(f"   ✅ Deleted schedule: {schedule['name']}")
                except Exception as e:
                    logger.error(f"   ❌ Failed to delete schedule {schedule['id']}: {e}")

    # Remove from favorites
    success = query_history.remove_from_favorites(query_id)

    if not success:
        raise HTTPException(status_code=404, detail="Favorite not found")

    return {
        "message": "✅ Removed from favorites",
        "query_id": query_id,
        "schedules_deleted": len(related_schedules) if schedules_db and force else 0
    }


@app.get("/history/stats")
async def get_history_stats():
    """Get query history statistics"""
    return query_history.get_stats()


@app.get("/dashboard.html", response_class=HTMLResponse)
async def dashboard_view_page():
    """Serve dashboard view page"""
    path = os.path.join(PROJECT_ROOT, 'frontend', 'dashboard.html')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Dashboard page not found</h1>", status_code=404)

@app.get("/ops-agent", response_class=HTMLResponse)
async def ops_agent_page():
    """BigQuery Ops Console"""
    ops_path = os.path.join(PROJECT_ROOT, 'frontend', 'ops-agents.html')
    try:
        with open(ops_path, 'r', encoding='utf-8') as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Ops Agent page not found</h1>", status_code=404)

@app.get("/file-analyzer", response_class=HTMLResponse)
async def file_analyzer_page():
    """Widget File Analyzer — anomaly detection UI"""
    page_path = os.path.join(PROJECT_ROOT, 'frontend', 'file-analyzer.html')
    try:
        with open(page_path, 'r', encoding='utf-8') as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>File Analyzer page not found</h1>", status_code=404)

@app.get("/dashboards.html", response_class=HTMLResponse)
async def dashboards_list_page():
    """Serve dashboards list page"""
    path = os.path.join(PROJECT_ROOT, 'frontend', 'dashboards.html')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Dashboards page not found</h1>", status_code=404)
# ============================================
# SCHEDULED QUERY EXECUTOR
# ============================================

async def execute_scheduled_query(query_id: str, user_id: str) -> dict:
    """
    Execute a query from favorites for scheduled execution

    Args:
        query_id: Favorite query ID
        user_id: User ID (for multi-tenant scenarios)

    Returns:
        dict with 'columns' and 'data'
    """
    try:
        # Get query from favorites
        favorite = None
        all_favorites = query_history.get_favorites(limit=1000)

        for fav in all_favorites:
            if fav['id'] == query_id:
                favorite = fav
                break

        if not favorite:
            raise ValueError(f"Query {query_id} not found in favorites")

        sql = favorite['sql']

        print(f"📅 Executing scheduled query: {favorite.get('question', 'Unnamed')}")

        # Execute SQL using current db_provider
        columns, data = db_provider.execute_query(sql)

        print(f"   ✅ Executed: {len(data)} rows returned")

        return {
            'columns': columns,
            'data': data
        }

    except Exception as e:
        print(f"   ❌ Execution failed: {e}")
        raise


# ============================================
# STARTUP & SHUTDOWN
# ============================================

@app.on_event("startup")
async def startup_event():
    """Initialize scheduled queries on startup"""
    global schedules_db, scheduler_manager, email_service

    print("\n🚀 Starting up SQLatte...")

    # Get scheduler config
    scheduler_config = config.get('scheduler', {})
    email_config = config.get('email', {})
    analytics_config = config.get('analytics', {})
    print("\n💡 Initializing Insights Engine...")
    try:
        current_config = config_manager.get_config()
        insights_config = current_config.get('insights', {})
        print(f"   Insights config from runtime: {insights_config}")

        initialize_insights_engine(
            llm_provider=llm_provider,
            enabled=insights_config.get('enabled', False),
            mode=insights_config.get('mode', 'hybrid'),
            max_insights=insights_config.get('max_insights', 4)
        )

        print("✅ Insights Engine initialized")
    except Exception as e:
        print(f"⚠️ Insights Engine init failed: {e}")

    # Initialize scheduled queries if enabled
    if scheduler_config.get('enabled', True):
        print("\n📅 Initializing Scheduled Queries...")

        try:
            # 1. Try PostgreSQL if analytics enabled
            use_persistent_jobstore = False
            postgres_url = None

            if analytics_config.get('enabled', False):
                try:
                    # Build PostgreSQL connection string
                    pg_config = analytics_config.get('postgresql', {})
                    postgres_url = (
                        f"postgresql://{pg_config.get('user', 'sqlatte')}:"
                        f"{pg_config.get('password', 'sqlatte')}@"
                        f"{pg_config.get('host', 'localhost')}:"
                        f"{pg_config.get('port', 5432)}/"
                        f"{pg_config.get('database', 'sqlatte_analytics')}"
                    )

                    print(f"   🔍 Attempting PostgreSQL connection...")
                    schedules_db = ScheduledQueriesDBPostgres(postgres_url)
                    await schedules_db.initialize()
                    use_persistent_jobstore = True
                    print("   ✅ Schedules database initialized (PostgreSQL - persistent)")

                except Exception as pg_error:
                    print(f"   ⚠️  PostgreSQL connection failed: {pg_error}")
                    print("   ↪️  Falling back to in-memory storage...")
                    schedules_db = ScheduledQueriesDB()
                    postgres_url = None
                    use_persistent_jobstore = False
                    print("   ✅ Schedules database initialized (in-memory - not persistent)")
            else:
                # Analytics disabled, use in-memory
                schedules_db = ScheduledQueriesDB()
                print("   ✅ Schedules database initialized (in-memory)")
                print("   💡 Tip: Enable analytics.enabled=true for persistent scheduler")

            # 2. Initialize email service
            if email_config.get('enabled', False):
                email_service = EmailService(email_config)
                print("   ✅ Email service initialized (SMTP)")
            else:
                email_service = MockEmailService(email_config)
                print("   ✅ Email service initialized (Mock mode - testing)")

            # 3. Initialize scheduler
            # NOTE: Always use in-memory jobstore for APScheduler
            # Schedules are persisted in scheduled_queries table instead
            # This avoids CronTrigger serialization issues with SQLAlchemy jobstore
            scheduler_manager = SchedulerManager(
                schedules_db=schedules_db,
                query_executor=execute_scheduled_query,
                email_service=email_service,
                timezone=scheduler_config.get('timezone', 'UTC'),
                use_persistent_store=False,  # Always False - use scheduled_queries table
                postgres_url=None
            )
            print(f"   ✅ Scheduler initialized (timezone: {scheduler_config.get('timezone', 'UTC')})")

            # 4. Start scheduler
            scheduler_manager.start()
            print("   ✅ Scheduler started")

            # 5. Load existing schedules
            await scheduler_manager.load_schedules()

            # 6. Make available to routes
            scheduled_routes.schedules_db = schedules_db
            scheduled_routes.scheduler_manager = scheduler_manager
            scheduled_routes.query_history_manager = query_history
            alarm_routes.scheduler_manager = scheduler_manager

            print("✅ Scheduled Queries initialized successfully!\n")

            # ── Ops Alarms ──────────────────────────────────────────
            alarms_config = config.get('alarms', {})
            if alarms_config.get('enabled', False):
                print("🔔 Initializing Ops Alarms...")
                try:
                    from src.core.provider_factory import get_ops_agent
                    alarm_svc = initialize_alarm_service(
                        config=alarms_config,
                        email_service=email_service,
                        ops_agent=get_ops_agent(),
                        jira_config=config.get('jira', {}),
                    )
                    for alarm in alarm_svc.alarms.values():
                        if alarm.enabled:
                            try:
                                from apscheduler.triggers.cron import CronTrigger
                                tz = scheduler_config.get('timezone', 'UTC')
                                scheduler_manager.scheduler.add_job(
                                    func=alarm_svc.evaluate_alarm,
                                    trigger=CronTrigger.from_crontab(alarm.schedule, timezone=tz),
                                    args=[alarm],
                                    id=f"alarm_{alarm.id}",
                                    replace_existing=True,
                                    name=f"alarm:{alarm.name}",
                                )
                                print(f"   ⏰ Scheduled: '{alarm.name}' ({alarm.schedule})")
                            except Exception as ae:
                                print(f"   ⚠️  Could not schedule '{alarm.name}': {ae}")
                    print(f"   ✅ Alarms ready ({len(alarm_svc.alarms)} defined)\n")
                except Exception as e:
                    print(f"   ⚠️  Alarms init failed: {e}")
            # ────────────────────────────────────────────────────────

        except Exception as e:
            print(f"❌ Failed to initialize Scheduled Queries: {e}")
            import traceback
            traceback.print_exc()
            print("   App will continue without scheduling functionality")
            schedules_db = None
            scheduler_manager = None
            email_service = None
    else:
        print("📅 Scheduled Queries disabled in config")
    # Dashboard Manager init
    print("\n📊 Initializing Dashboard Manager...")
    try:
        initialize_dashboard_manager(analytics_db=analytics_db)
        print("✅ Dashboard Manager initialized")
    except Exception as e:
        print(f"⚠️ Dashboard Manager init failed: {e}")
        # Fallback to in-memory
        initialize_dashboard_manager(analytics_db=None)
        print("✅ Dashboard Manager initialized (in-memory fallback)")
    # ==========================================
    # ✅ ADD THIS: SEMANTIC LAYER INITIALIZATION
    # ==========================================
    print("\n🧠 Initializing Semantic Layer...")
    try:
        from src.core.semantic_layer_db import get_semantic_layer_db

        current_config = config_manager.get_config()
        db_config = current_config.get('config_db', {})

        if db_config.get('enabled'):
            # Pass full config to function
            semantic_db = get_semantic_layer_db(
                config=current_config,
                use_memory=False
            )

            # Get stats
            entities = semantic_db.get_entities()
            relationships = semantic_db.get_relationships()
            metrics = semantic_db.get_metrics()

            print(f"✅ Semantic Layer initialized (PostgreSQL)")
            print(f"   └─ Entities: {len(entities)}")
            print(f"   └─ Relationships: {len(relationships)}")
            print(f"   └─ Metrics: {len(metrics)}")

            app.state.semantic_db = semantic_db
        else:
            print("⚠️  Semantic Layer disabled (config_db.enabled = false)")
            app.state.semantic_db = None

    except Exception as e:
        print(f"⚠️  Semantic Layer failed: {e}")
        import traceback
        traceback.print_exc()
        app.state.semantic_db = None
    print("✅ SQLatte startup complete!\n")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    print("\n🛑 Shutting down SQLatte...")

    # Shutdown scheduler
    if scheduler_manager:
        print("📅 Stopping scheduler...")
        scheduler_manager.shutdown()
        print("   ✅ Scheduler stopped")

    # Shutdown email service (wait for pending emails)
    if email_service:
        print("📧 Shutting down email service...")
        email_service.shutdown(timeout=30)
        print("   ✅ Email service stopped")

    # Close thread pool
    MAIN_EXECUTOR.shutdown(wait=True)
    print("✅ Thread pool closed")

    print("✅ Shutdown complete\n")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=config['app']['host'],
        port=config['app']['port'],
        log_level="info"
    )