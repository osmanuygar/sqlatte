# SQLatte ☕
AI-powered natural language to SQL converter. Modern web app to convert natural language to SQL queries using large language models (LLMs) like Anthropic and OpenAI. Supports multiple databases including Postgres, MySQL, Trino, and SQLite.


[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/downloads/release/python-380/)


## Features

- 🤖 **LLM Integration** - Anthropic, OpenAI, etc.
- 🗄️ **DB Support** - Postgres, MySQL, Trino, SQLite
- 📦 **Modular Frontend** - Reusable CSS/JS
- ⚙️ **Simple Config** - Single YAML file
- 🗣️ **Smart Chat** - SQL + conversation
- 🔗 **Multi-table JOINs** - Automatic detection
- 🐳 **Docker Ready** - Easy deployment

## Quick Start

```bash
cd sqlatte/
pip install -r requirements.txt

# Edit config/config.yaml (add API key)
nano config/config.yaml

python run.py
```

**Open:** http://localhost:8000

## Configuration

**Edit `config/config.yaml`:**
```yaml
llm:
  anthropic:
    api_key: "sk-ant-your-key-here"

database:
  trino:
    host: "trino.example.com"
    user: "username"
    password: "password"
```

**That's it!** No .env file needed.

## Reusable Components

Use SQLatte UI in your app:

```html
<link rel="stylesheet" href="http://localhost:8000/static/css/style.css">
<script src="http://localhost:8000/static/js/app.js"></script>
```
## Docker Deployment     

```bash
docker build -t sqlatte .
docker run -d -p 8000:8000 --name sqlatte sqlatte
```


## 📄 License

MIT License

---

**Made with ❤ and ☕**
