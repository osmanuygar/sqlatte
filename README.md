# SQLatte ☕

<p align="center">
  <img src="frontend/static/image/sqlatte_logo.svg" width="150" alt="SQLatte Logo">
</p>

<p align="center">
  <strong>AI-Powered Natural Language to SQL Converter with Conversation Memory</strong><br>
  Transform your questions into SQL queries with the power of AI - Now with conversation memory! 🧠
</p>

<p align="center">
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT">
  <img src="https://img.shields.io/badge/python-3.8%2B-blue.svg" alt="Python 3.8+">
  <img src="https://img.shields.io/badge/AI-Anthropic%20Claude-blueviolet" alt="AI: Anthropic Claude">
  <img src="https://img.shields.io/badge/Memory-Conversation%20Tracking-green" alt="Conversation Memory">
</p>

---

##  Features

### Core Features
- 🤖 **AI-Powered** - Uses Anthropic Claude, Google Gemini, or Google Vertex AI
- 🗄️ **Multi-Database Support** - Trino, PostgreSQL, MySQL, and more
- 💬 **Smart Chat Interface** - Conversational AI that understands context
- 🔗 **Multi-Table JOINs** - Automatically detects and creates table relationships
- 🧠 **Conversation Memory** - Remembers chat history per session (in-memory)
- 🎯 **Context-Aware Responses** - Understands follow-up questions
- 📱 **Widget-Based UI** - Fullscreen modal with modern, responsive design
- ⚡ **Fast & Simple** - Single YAML config file, no complex setup
- 🐳 **Docker Ready** - Easy deployment with Docker & Docker Compose

---

##  Quick Start

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/osmanuygar/sqlatte.git
cd sqlatte

# Install dependencies
pip install -r requirements.txt
```

### 2. Configuration

Edit `config/config.yaml` with your credentials:

```yaml
# LLM Configuration
llm:
  provider: "anthropic"
  anthropic:
    api_key: "sk-ant-your-key-here"  # Add your Anthropic API key
    model: "claude-sonnet-4-20250514"

# Database Configuration
database:
  provider: "trino"
  trino:
    host: "your-trino-host.com"
    port: 443
    user: "your-username"
    password: "your-password"
    catalog: "hive"
    schema: "default"
```

### 3. Run

```bash
# Start the server
python run.py

# Open in browser
http://localhost:8000
```

**That's it!** 🎉


---

## 🎨 Architecture

### Backend Flow with Memory

```
User Question
     ↓
Session Management (Get/Create Session)
     ↓
Add to Conversation History
     ↓
Get Recent Context (Last 10 messages)
     ↓
LLM Intent Detection + Context
     ↓
   ┌─────────────┬──────────────┐
   │             │              │
  SQL          Chat         Schema
   │             │              │
Generate      Generate      Fetch from DB
 Query        Response
(with context)  (with context)
   │             │
Execute       Return
   │             │
   └──────┬──────┘
          ↓
    Add Response to History
          ↓
    Return to User
```

---

## 🐳 Docker Deployment

### Using Docker Compose (Recommended)

```bash
# 1. Edit config/config.yaml and set your credentials
vi config/config.yaml

# 2. Start with Docker Compose
docker-compose up -d

# 3. Open browser
http://localhost:8000
```

### Using Dockerfile

```bash
# Build image
docker build -t sqlatte .

# Run container
docker run -d -p 8000:8000 \
  -e ANTHROPIC_API_KEY="your-key" \
  -e TRINO_HOST="your-host" \
  --name sqlatte \
  sqlatte
```

---

## 🔌 Embedding in Your Website

You can easily add the SQLatte widget to **any existing website**.

### Method 1: Serve from SQLatte Backend (Recommended)

**Easiest way!** SQLatte backend already serves the widget files:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>My Website with SQLatte</title>
</head>
<body>
    <h1>My Awesome Website</h1>
    <p>Your content here...</p>

    <!-- Load widget from SQLatte backend -->
    <script src="http://YOUR-SQLATTE-SERVER:8000/static/js/sqlatte-badge.js"></script>
    
    <!-- Configure (optional) -->
    <script>
        window.addEventListener('load', () => {
            window.SQLatteWidget.configure({
                fullscreen: true,
                apiBase: 'http://YOUR-SQLATTE-SERVER:8000'
            });
        });
    </script>
</body>
</html>
```

#### CORS Configuration

If your website and SQLatte are on **different domains**, configure CORS in `config/config.yaml`:

```yaml
cors:
  allow_origins: 
    - "https://your-website.com"
    - "http://192.168.1.50"
  allow_credentials: true
  allow_methods: ["*"]
  allow_headers: ["*"]
```

---

## ⚙️ Widget Configuration

Customize the widget behavior:

```javascript
window.SQLatteWidget.configure({
    // Position of the badge button
    position: 'bottom-right',  // 'bottom-right', 'bottom-left', 'top-right', 'top-left'
    
    // Open modal in fullscreen
    fullscreen: true,          // true = fullscreen, false = floating modal
    
    // Modal title
    title: 'SQLatte Assistant ☕',
    
    // Input placeholder text
    placeholder: 'Ask a question...',
    
    // API base URL (SQLatte backend)
    apiBase: 'http://your-backend:8000',
    
    // Delay before showing badge (milliseconds)
    autoShowDelay: 1000,
    
    // Open widget automatically on page load
    openByDefault: false
});
```

### Programmatic Control

```javascript
// Open the widget
window.SQLatteWidget.open();

// Close the widget
window.SQLatteWidget.close();

// Toggle widget
window.SQLatteWidget.toggle();

// Clear conversation history
window.SQLatteWidget.clearChat();

// Get current session ID
const sessionId = window.SQLatteWidget.getSessionId();
```

---

## 🗄️ Supported Databases

### Currently Supported
- ✅ **Trino** - Distributed SQL engine
- ✅ **PostgreSQL** - Advanced relational database
- ✅ **MySQL** - Popular relational database

### Configuration Examples

<details>
<summary><b>Trino Configuration</b></summary>

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
<summary><b>PostgreSQL Configuration</b></summary>

```yaml
database:
  provider: "postgresql"
  postgresql:
    host: "localhost"
    port: 5432
    database: "mydatabase"
    user: "postgres"
    password: "password"
    schema: "public"
```
</details>

<details>
<summary><b>MySQL Configuration</b></summary>

```yaml
database:
  provider: "mysql"
  mysql:
    host: "localhost"
    port: 3306
    database: "mydatabase"
    user: "root"
    password: "password"
```
</details>

---

## 🤖 Supported LLM Providers

### Currently Supported
- ✅ **Anthropic Claude** - Most advanced (recommended)
- ✅ **Google Gemini** - Free tier available
- ✅ **Google Vertex AI** - Enterprise GCP solution

### Configuration Examples

<details>
<summary><b>Anthropic Claude</b></summary>

```yaml
llm:
  provider: "anthropic"
  anthropic:
    api_key: "sk-ant-your-key-here"
    model: "claude-sonnet-4-20250514"
    max_tokens: 1000
```
</details>

<details>
<summary><b>Google Gemini</b></summary>

```yaml
llm:
  provider: "gemini"
  gemini:
    api_key: "your-gemini-key"
    model: "gemini-pro"
    max_tokens: 1000
```
</details>

<details>
<summary><b>Google Vertex AI</b></summary>

```yaml
llm:
  provider: "vertexai"
  vertexai:
    project_id: "my-gcp-project"
    location: "us-central1"
    model: "gemini-pro"
    credentials_path: "/path/to/service-account.json"
```
</details>

---

---

## Changelog

### v0.2.0 (Latest) - Conversation Memory
- 🧠 Added conversation memory system
- 💬 Session-based chat tracking
- 🎯 Context-aware responses
- 🗑️ Clear chat functionality
- 📊 Conversation analytics endpoints

### v0.1.0 - Initial Release
- 🤖 Multi-LLM support (Anthropic, Gemini, Vertex AI)
- 🗄️ Multi-database support (Trino, PostgreSQL, MySQL)
- 💬 Smart chat interface
- 🔗 Multi-table JOIN support
- 📱 Embeddable widget

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---


## 📧 Contact

- **GitHub:** [@osmanuygar](https://github.com/osmanuygar)
- **Project Link:** [https://github.com/osmanuygar/sqlatte](https://github.com/osmanuygar/sqlatte)

---

<p align="center">
  <strong>Made with ❤️ and ☕</strong><br>
  <sub>Transform your data queries with the power of AI and conversation memory</sub>
</p>

---
