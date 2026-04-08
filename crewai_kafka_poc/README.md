# CrewAI + Kafka Topic Automation PoC

This PoC demonstrates an **AI workflow automation** project for teammates:

- **FastAPI** exposes Kafka topic data via REST endpoints.
- **CrewAI** runs a two-agent workflow to create an operational report from topic names.
- Includes **mock fallback mode** so the demo works even without a live Kafka cluster.

## Project Structure

```text
crewai_kafka_poc/
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── crew_workflow.py
│   ├── kafka_service.py
│   ├── main.py
│   └── models.py
├── .env.example
├── requirements.txt
└── README.md
```

## API Endpoints

- `GET /health` - health check
- `GET /api/topics` - returns Kafka topics (real Kafka or mock fallback)
- `POST /api/workflows/topic-report` - runs CrewAI workflow and returns report

## Quick Start

### 1) Install dependencies

```bash
cd crewai_kafka_poc
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) Configure environment

```bash
cp .env.example .env
```

Optional:
- Set `OPENAI_API_KEY` in `.env` for real LLM output from CrewAI.
- Set `KAFKA_BOOTSTRAP_SERVERS` to your cluster (e.g. `localhost:9092`).

### 3) Run API

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

### 4) Call endpoints

List topics:

```bash
curl -s http://127.0.0.1:8001/api/topics | jq
```

Run CrewAI workflow:

```bash
curl -s -X POST "http://127.0.0.1:8001/api/workflows/topic-report" \
  -H "Content-Type: application/json" \
  -d '{"question":"Which topics look risky for production and why?"}' | jq
```

## How fallback mode works

If Kafka or CrewAI cannot run, the service still returns useful output:

- Kafka errors -> returns `source: "mock"` and mock topics from `MOCK_TOPICS_CSV`.
- CrewAI errors -> returns a deterministic fallback report.

This makes the PoC stable for demos.

## Notes for teammate demos

1. Start with mock mode (works instantly).
2. Switch to real Kafka by updating `KAFKA_BOOTSTRAP_SERVERS`.
3. Add an LLM API key to get fully AI-generated reports from CrewAI.
