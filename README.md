# SQLatte ☕

<p align="center">
  <img src="frontend/static/image/sqlatte_logo.svg" width="150" alt="SQLatte Logo">
</p>

<p align="center">
  <strong>SQLatte - Enterprise-Grade Natural Language SQL Analytics Platform</strong><br>
  Production-ready self-service analytics with AI-powered query generation, semantic layer, automated dashboards, and scheduled insights delivery.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT">
  <img src="https://img.shields.io/badge/python-3.8%2B-blue.svg" alt="Python 3.8+">
  <img src="https://img.shields.io/badge/AI-Anthropic%20Claude-blueviolet" alt="AI: Anthropic Claude">
  <img src="https://img.shields.io/badge/Status-Production-green" alt="Production Ready">
</p>

<p align="center">
    <img src="frontend/static/image/sqlatte.png" width="800" alt="SQLatte">
   </p>

---

## ✨ What is SQLatte?

SQLatte transforms natural language questions into SQL queries using AI, providing enterprise-grade analytics capabilities without requiring SQL knowledge. Built for production environments with security, scalability, and ease of deployment in mind.

**Key Capabilities:**

- 🤖 **AI-Powered Query Generation** - Natural language to SQL conversion
- 🧠 **Semantic Layer** - Business-friendly metadata layer over your data warehouse
- 📊 **Auto Dashboard Generation** - Visual reports from query results
- 📅 **Query Scheduler** - Automated report delivery via email
- 🔐 **Multi-Tenant Auth** - User-specific database connections
- 📈 **AI Insights Engine** - Automatic data analysis and pattern detection
- 🔧 **BigQuery Ops Console** - Cost optimization, security audits, and performance diagnostics
- ⏰ **Ops Alarms** - Scheduled cost threshold alarms with email and Jira notifications
- 📋 **Audit Logs** - Full LLM call tracing with token usage, widget source (default/auth/MCP), and CSV export
- 🔌 **MCP Server** - Native Claude Desktop integration via `sqlatte_mcp_server.py`
- 🗄️ **Multi-Database Support** - Trino, PostgreSQL, MySQL, BigQuery
- 🎨 **Embeddable Widgets** - Easy integration into existing applications

---

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     Frontend Layer                          │
│  • Chat Interface  • Admin Panel  • Embeddable Widgets     │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│                   API Layer (FastAPI)                       │
│  • Query Routes  • Admin Routes  • Analytics  • Scheduler  │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│              Core Processing Layer                          │
│  • Intent Detection  • SQL Generation  • Query Execution   │
│  • Insights Engine  • Dashboard Generator                   │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│         Database Provider Factory                           │
│  (Trino │ PostgreSQL │ MySQL │ BigQuery)                   │
└─────────────────────────────────────────────────────────────┘
```

---

## 🚀 Features

### Core Analytics Platform

- **🎯 Task-Based LLM Routing** - Different AI models for different tasks (intent detection, SQL generation, insights)
- **💬 Conversation Memory** - Context-aware follow-up questions
- **🔗 Multi-Table JOINs** - Automatic relationship detection
- **📊 Query History & Favorites** - Save and replay queries
- **🔍 SQL Syntax Highlighting** - Beautiful code display with copy functionality
- **📈 CSV Export** - Export results to spreadsheet format

### Semantic Layer (🆕 v0.5.0)

Transform your data warehouse with business intelligence metadata:

- **🧠 Business-Friendly Names** - "Customer Master" instead of "cust_tbl_v2"
- **🔗 Automatic JOINs** - Define relationships once, AI uses them automatically
- **📈 Calculated Metrics** - Centralized business logic (everyone gets same "revenue")
- **🔍 Auto-Discovery** - Scan database and get instant entity suggestions
- **🎨 Visual Admin UI** - Browser-based management with entity/relationship/metric builder
- **🤖 Enhanced AI Context** - Richer metadata = better SQL generation

### Dashboard System

- **📊 Auto Chart Generation** - Line, bar, pie charts from query results
- **💳 Metric Cards** - KPI displays with automatic formatting
- **🎨 Chart Configuration** - Customize chart types and settings
- **💾 Dashboard Persistence** - Save dashboards to PostgreSQL or in-memory
- **🔄 One-Click Refresh** - Re-run queries and update visualizations

### AI-Powered Insights Engine

- **🧠 Context-Aware Analysis** - Considers temporal patterns (daily, weekly, monthly)
- **📈 Trend Detection** - Growth, decline, anomaly identification
- **💡 Smart Recommendations** - Actionable insights from your data
- **⚙️ Flexible Modes** - `llm_only`, `statistical_only`, or `hybrid`
- **🎯 Query-Specific Context** - Insights tailored to your question

### BigQuery Ops Console

Operational automation for BigQuery environments, accessible at `/ops-agent`:

- **💰 Cost Analysis** - Identify expensive queries, forecast monthly spend, analyze storage compression, detect unpartitioned tables, and compare on-demand vs flat-rate billing
- **🔒 Security Audits** - Find public datasets, review table permissions, and audit service account usage
- **⚡ Performance Diagnostics** - Surface slow queries, data skew, slot saturation, full table scans, and partition recommendations
- **🏛️ Governance** - Track unused tables and recent table access
- **🤖 AI Insights** - Optional AI-generated findings per operation, prompt-configurable via `ops_insights_generation` in `config.yaml`
- **🔀 Multi-Project Support** - Switch between GCP projects at runtime
- **⏰ Cost Alarms** - Schedule threshold-based alarms (e.g. >0.5 TB processed) with cron triggers, email and Jira notifications, and test-on-demand

```yaml
ops_agent:
  enabled: true
  ai_insights: true       # enable AI findings per operation
  ai_insights_max: 5
  config:
    projects:
      - project_id: "my-project"
        region: "europe-west1"
        credentials_path: "/path/to/service-account.json"
```

### Audit Logs

Every LLM call is recorded for observability and cost tracking:

- **📋 Full Tracing** - Logs intent detection, SQL generation, chat, and insights calls with input/output token counts
- **🔍 Filtering** - Filter by session, intent type, date range, or user
- **📊 Summary Stats** - Aggregated token usage and call counts
- **📥 CSV Export** - Download audit data for billing or compliance analysis
- **🔍 Admin UI** - Dedicated Audit Logs tab in the admin panel at `/admin`

### Query Scheduler

- **📅 Flexible Scheduling** - Hourly, daily, weekly, monthly, or custom cron
- **📧 Email Delivery** - Automated report distribution with CSV/Excel/HTML attachments
- **🤖 AI-Generated Insights** - Include analysis in scheduled reports
- **📊 Execution History** - Track all scheduled query runs
- **⚡ Rate Limiting** - Prevent spam and manage resources

### Security & Authentication

- **🔐 SQL Injection Protection** - Multi-layer validation with risk scoring
- **🔑 Session-Based Auth** - Token-based authentication for admin endpoints
- **👤 Multi-Tenant Support** - Per-user database connections via auth plugin
- **🛡️ Catalog/Schema Restrictions** - Limit user access to specific databases
- **🔒 Credential Masking** - Secure password handling in logs and UI

### Admin Panel

- **⚙️ Runtime Configuration** - Edit settings without restart
- **📝 Prompt Management** - Customize AI behavior via UI
- **🔧 Config Database** - Persist settings to PostgreSQL
- **📸 Snapshots** - Backup and restore configurations
- **📜 Change History** - Track configuration modifications

### Embeddable Widgets

Two widget variants for different use cases:

- **Standard Widget** (`sqlatte-badge.js`) - Public analytics interface
- **Auth Widget** (`sqlatte-badge-auth.js`) - User-specific database connections

---

## 📦 Quick Start

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/osmanuygar/sqlatte.git
cd sqlatte

# Install dependencies
pip install -r requirements.txt
```

### 2. Configuration

Edit `config/config.yaml`:

```yaml
# ============================================
# LLM CONFIGURATION
# ============================================
llm:
  provider: "anthropic"  # anthropic | gemini | vertexai
  anthropic:
    api_key: "sk-ant-your-key-here"
    model: "claude-sonnet-4-20250514"
    max_tokens: 4096

# ============================================
# DATABASE CONFIGURATION
# ============================================
database:
  provider: "trino"  # trino | postgresql | mysql | bigquery
  trino:
    host: "your-trino-host.com"
    port: 443
    user: "your-username"
    password: "your-password"
    catalog: "hive"
    schema: "default"
    http_scheme: "https"

# ============================================
# TASK-BASED LLM ROUTING (Optional)
# ============================================
# Use cheaper/faster models for simple tasks
model_routing:
  enabled: true
  tasks:
    intent_detection:
      provider: "anthropic"
      model: "claude-haiku-3-5-20241022"
      max_tokens: 500

    sql_generation:
      provider: "anthropic"
      model: "claude-sonnet-4-20250514"
      max_tokens: 4096

    insights:
      provider: "anthropic"
      model: "claude-sonnet-4-20250514"
      max_tokens: 2000

    chat:
      provider: "anthropic"
      model: "claude-haiku-3-5-20241022"
      max_tokens: 1000

# ============================================
# FEATURES (All Optional)
# ============================================
analytics:
  enabled: false  # Set true for PostgreSQL query history

scheduler:
  enabled: false  # Set true for scheduled queries
  timezone: "UTC"

email:
  enabled: false  # Set true for real email delivery
  smtp:
    host: "smtp.gmail.com"
    port: 587
    user: "your-email@gmail.com"
    password: "your-app-password"
    from_name: "SQLatte Analytics"

insights:
  enabled: true
  mode: hybrid  # llm_only | statistical_only | hybrid
  max_insights: 3

# ============================================
# CONFIGURATION DATABASE (Optional)
# ============================================
config_db:
  enabled: false  # Enable for runtime config persistence
  type: "postgresql"
  postgresql:
    host: "localhost"
    port: 5432
    database: "sqlatte_config"
    user: "postgres"
    password: "password"

# ============================================
# PLUGINS (Optional)
# ============================================
plugins:
  auth:
    enabled: false  # Enable for multi-tenant auth
    session_ttl_minutes: 480
    max_workers: 40
    db_provider: "trino"
    db_host: "trino_hostname"
    db_port: 443
    allowed_catalogs: []  # Empty = allow all
    allowed_schemas: []
    allowed_db_types: ["trino"]
```

### 3. Run

```bash
# Development
python -m src.api.app

# Production (with Gunicorn)
gunicorn src.api.app:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
```

### 4. Access

- **Main Interface**: http://localhost:8000
- **Admin Panel**: http://localhost:8000/admin
- **Widget Demo**: http://localhost:8000/demo
- **API Docs**: http://localhost:8000/docs

---

## 🐳 Docker Deployment

### Using Docker Compose (Recommended)

```bash
# 1. Edit config/config.yaml with your credentials
vi config/config.yaml

# 2. Start services
docker-compose up -d

# 3. Open browser
open http://localhost:8000
```

### Using Dockerfile

```bash
# Build image
docker build -t sqlatte .

# Run container
docker run -d -p 8000:8000 \
  -e ANTHROPIC_API_KEY="sk-ant-your-key" \
  -e TRINO_HOST="your-trino-host" \
  -e TRINO_USER="username" \
  -e TRINO_PASSWORD="password" \
  --name sqlatte \
  sqlatte
```

---

## 🗄️ Supported Databases


| Database      | Status | Configuration Required       |
| ------------- | ------ | ---------------------------- |
| ✅ Trino      | Stable | host, port, catalog, schema  |
| ✅ PostgreSQL | Stable | host, port, database, schema |
| ✅ MySQL      | Stable | host, port, database         |
| ✅ BigQuery   | Stable | project_id, credentials      |

<details>
<summary><b>Trino Configuration Example</b></summary>

```yaml
database:
  provider: "trino"
  trino:
    host: "trino.example.com"
    port: 443
    user: "username"
    password: "password"
    catalog: "hive"
    schema: "default"
    http_scheme: "https"
```

</details>

<details>
<summary><b>PostgreSQL Configuration Example</b></summary>

```yaml
database:
  provider: "postgresql"
  postgresql:
    host: "localhost"
    port: 5432
    database: "analytics"
    user: "postgres"
    password: "password"
    schema: "public"
```

</details>

<details>
<summary><b>BigQuery Configuration Example</b></summary>

```yaml
database:
  provider: "bigquery"
  bigquery:
    project_id: "my-gcp-project"
    dataset: "analytics"
    location: "US"
    credentials_path: "/path/to/service-account.json"
    # OR: credentials_json: '{"type": "service_account", ...}'
```

</details>

---

## 🤖 Supported LLM Providers


| Provider            | Models              | Best For                        |
| ------------------- | ------------------- | ------------------------------- |
| ✅ Anthropic Claude | Opus, Sonnet, Haiku | Most accurate SQL (recommended) |
| ✅ Google Gemini    | gemini-pro          | Free tier available             |
| ✅ Google Vertex AI | gemini-pro          | Enterprise GCP                  |

---

## 🔌 Embedding in Your Website

### Standard Widget (Public Analytics)

```html
<!DOCTYPE html>
<html>
<body>
    <h1>My Website</h1>

    <!-- Load widget from SQLatte backend -->
    <script src="http://your-sqlatte-server:8000/static/js/sqlatte-badge.js"></script>

    <!-- Configure (optional) -->
    <script>
        window.addEventListener('load', () => {
            window.SQLatteWidget.configure({
                position: 'bottom-right',
                fullscreen: true,
                apiBase: 'http://your-sqlatte-server:8000'
            });
        });
    </script>
</body>
</html>
```

### Auth Widget (User-Specific Connections)

```html
<!DOCTYPE html>
<html>
<body>
    <h1>My SaaS Application</h1>

    <!-- Load auth widget -->
    <script src="http://your-sqlatte-server:8000/static/js/sqlatte-badge-auth.js"></script>

    <!-- Configure -->
    <script>
        window.addEventListener('load', () => {
            window.SQLatteAuthWidget.configure({
                position: 'bottom-left',
                fullscreen: true,
                apiBase: 'http://your-sqlatte-server:8000'
            });
        });
    </script>
</body>
</html>
```

### CORS Configuration

If embedding on a different domain:

```yaml
cors:
  allow_origins:
    - "https://your-website.com"
    - "http://localhost:3000"
  allow_credentials: true
  allow_methods: ["*"]
  allow_headers: ["*"]
```

---

## 📊 Usage Examples

### Basic Query

```
User: "Show me top 10 customers by revenue this year"

SQLatte:
💡 Generated SQL:
SELECT customer_name, SUM(order_total) as revenue
FROM orders
WHERE YEAR(order_date) = YEAR(CURRENT_DATE)
GROUP BY customer_name
ORDER BY revenue DESC
LIMIT 10

📊 Results: [Interactive table with 10 rows]

🧠 Insights:
- Top customer generated $1.2M (23% of total revenue)
- Revenue concentration in top 3 customers indicates dependency risk
- Consider diversification strategy
```

### Follow-up Question

```
User: "What about last year?"

SQLatte: [Automatically understands context, modifies WHERE clause]
```

### Dashboard Creation

```
User: "Create a dashboard for this query"

SQLatte: [Generates line chart + metric cards + saves to favorites]
```

---

## 🎯 Advanced Features

### Semantic Layer

Define business metadata once, use everywhere:

```yaml
# Example: Define a "Customer" entity
Entity: customer_master
Display Name: Customer
Description: Core customer data
Columns:
  - cust_id (Primary Key)
  - full_name (Display Name: Customer Name)
  - registration_date
  - ltv (Display Name: Lifetime Value)

# Define relationship
Relationship: customer_to_orders
From: customer_master.cust_id
To: orders.customer_id
Type: one-to-many

# Define metric
Metric: total_revenue
SQL: SUM(orders.amount)
Description: Total revenue across all orders
```

Now ask: **"Show me customers with high lifetime value"**

SQLatte automatically:

1. Uses "Customer" display name
2. Finds the correct table (customer_master)
3. Interprets "lifetime value" as the ltv column
4. Generates accurate SQL with proper column references

### Query Scheduler

Schedule recurring reports:

```yaml
Schedule Name: Weekly Revenue Report
Frequency: Weekly (Every Monday 9 AM)
Recipients: analytics-team@company.com
Format: Excel with AI insights
```

### Task-Based Model Routing

Optimize costs and performance:

```yaml
# Cheap/fast model for simple tasks
intent_detection: claude-haiku (500 tokens)

# Powerful model for complex SQL
sql_generation: claude-sonnet (4096 tokens)

# Balanced model for insights
insights: claude-sonnet (2000 tokens)
```

---

## 🔧 Admin Panel Features

Access at `/admin`:

### 🎨 Tabs

1. **Dashboard** - Overview, stats, quick actions
2. **Prompts** - Edit AI behavior (intent, personality, SQL generation, insights)
3. **Tables** - View database schema
4. **Semantic Layer** - Entity/relationship/metric builder (5 sub-tabs)
5. **Email & SMTP** - Email configuration
6. **Scheduler** - Scheduled query management
7. **Insights** - Insights engine settings
8. **Ops Agent** - BigQuery Ops Console toggles, AI insights settings, and cost alarms
9. **Export** - Configuration export formats
10. **History** - Configuration change log
11. **Snapshots** - Backup and restore
12. **Audit Logs** - LLM call history with token usage, filterable by widget source (default / auth / MCP)

### Key Capabilities

- **Hot Reload** - Changes apply immediately without restart
- **Database Persistence** - Save configs to PostgreSQL
- **Reset to Defaults** - One-click restore original settings
- **Semantic Auto-Discovery** - Scan database and suggest entities
- **Visual Relationship Builder** - Drag-and-drop table connections

---

## 🔐 Security Features

### SQL Injection Protection

Multi-layer validation:

1. **Keyword Blacklist** - Block dangerous SQL patterns
2. **Syntax Validation** - Parse and validate SQL structure
3. **Risk Scoring** - Assign risk level to each query
4. **Admin Override** - Manual approval for high-risk queries

### Rate Limiting

```yaml
rate_limiting:
  enabled: true
  requests_per_minute: 10
  requests_per_hour: 100
```

### Authentication Plugin

Multi-tenant database access:

- User-specific credentials
- Catalog/schema restrictions
- Session management with TTL
- Thread-safe connection pooling

---

## 📈 Performance & Scalability

### Async Processing

- FastAPI with async/await
- Thread pool for blocking operations
- Non-blocking query execution

### Connection Pooling

- Reusable database connections
- Automatic cleanup on timeout
- Thread-safe multi-user support

### Caching

- Query result caching
- Dashboard persistence
- Session-based conversation memory

---

---

## 🔌 MCP Server (Claude Desktop Integration)

Use SQLatte directly from Claude Desktop or Claude Code via the Model Context Protocol:

```bash
pip install mcp httpx
```

### Option A — API Token (Recommended)

Keeps real database credentials out of MCP config. Token is generated from the SQLatte UI and stores the connection details server-side (encrypted).

**1. Generate a token:**

Login to SQLatte → open the chat widget → click **🔑 API Tokens** → Generate.
Copy the token (shown only once).

**2. Add to Claude config:**

```json
{
  "mcpServers": {
    "sqlatte": {
      "command": "python3",
      "args": ["/path/to/sqlatte/sqlatte_mcp_server.py"],
      "env": {
        "SQLATTE_URL": "http://localhost:8000",
        "SQLATTE_TOKEN": "<token>"
      }
    }
  }
}
```

Token TTL is configurable (24h default). Each user generates their own token — the token carries their catalog/schema context.

### Option B — Username / Password (Legacy)

```json
{
  "mcpServers": {
    "sqlatte": {
      "command": "python3",
      "args": ["/path/to/sqlatte/sqlatte_mcp_server.py"],
      "env": {
        "SQLATTE_URL": "http://localhost:8000",
        "TRINO_HOST": "your-trino-host",
        "TRINO_PORT": "443",
        "TRINO_USER": "your-username",
        "TRINO_PASSWORD": "your-password",
        "TRINO_CATALOG": "hive",
        "TRINO_SCHEMA": "default",
        "TRINO_HTTP_SCHEME": "https"
      }
    }
  }
}
```

Available tools: **`ask_database`** (natural language → SQL → results), **`list_tables`**, **`get_schema`**.

---

## 🤝 Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit changes (`git commit -m 'Add AmazingFeature'`)
4. Push to branch (`git push origin feature/AmazingFeature`)
5. Open Pull Request

---

## 📄 License

This project is licensed under the MIT License - see [LICENSE](LICENSE) file.

---

## 📧 Contact

- **GitHub**: [@osmanuygar](https://github.com/osmanuygar)
- **Project**: [https://github.com/osmanuygar/sqlatte](https://github.com/osmanuygar/sqlatte)

---

## 🙏 Acknowledgments

Built with:

- FastAPI - Modern Python web framework
- Anthropic Claude - AI-powered query generation
- Chart.js - Data visualization
- PostgreSQL - Data persistence
- Trino, BigQuery - Analytics engines

---

## 📚 Documentation

- **Docs**: [Documentation](https://osmanuygar.github.io/sqlatte-docs)

---

<p align="center">
  <strong>Made with ❤️ and ☕</strong><br>
  <sub>Transform your data warehouse into a conversational analytics platform</sub>
</p>
