from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .crew_workflow import CrewAIKafkaWorkflow
from .kafka_service import KafkaTopicService
from .models import (
    TopicListResponse,
    WorkflowBlueprintResponse,
    WorkflowRequest,
    WorkflowResponse,
)

settings = get_settings()
topic_service = KafkaTopicService(settings=settings)
workflow_service = CrewAIKafkaWorkflow(settings=settings)

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="PoC API that combines Kafka topic discovery with CrewAI reporting.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "message": "CrewAI Kafka PoC is running.",
        "topics_endpoint": "/api/topics",
        "workflow_endpoint": "/api/workflows/topic-report",
        "workflow_blueprint_endpoint": "/api/workflows/blueprint",
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.app_env}


@app.get("/api/topics", response_model=TopicListResponse)
def list_topics() -> TopicListResponse:
    return topic_service.list_topics()


@app.get("/api/workflows/blueprint", response_model=WorkflowBlueprintResponse)
def workflow_blueprint() -> WorkflowBlueprintResponse:
    blueprint = workflow_service.get_workflow_blueprint()
    return WorkflowBlueprintResponse(
        workflow_name="Kafka Topic Automation Crew",
        process=str(blueprint["process"]),
        roles=[str(role) for role in blueprint["roles"]],
        description=(
            "Sequential CrewAI workflow with Solution Architect -> Coder -> Tester "
            "roles for Kafka topic automation planning."
        ),
    )


@app.post("/api/workflows/topic-report", response_model=WorkflowResponse)
def create_topic_report(payload: WorkflowRequest) -> WorkflowResponse:
    topic_response = topic_service.list_topics()
    question = payload.question or settings.default_workflow_question
    workflow_result = workflow_service.run(topics=topic_response.topics, question=question)

    return WorkflowResponse(
        source=topic_response.source,
        topics=topic_response.topics,
        topic_count=topic_response.topic_count,
        question=question,
        workflow_roles=workflow_service.WORKFLOW_ROLES,
        execution_mode=workflow_result["execution_mode"],
        report=workflow_result["report"],
    )
