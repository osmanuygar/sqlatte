from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, Field


class TopicListResponse(BaseModel):
    source: str = Field(
        description="`kafka` when fetched from cluster, `mock` when fallback is used."
    )
    topics: List[str]
    topic_count: int
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error: Optional[str] = None


class WorkflowRequest(BaseModel):
    question: Optional[str] = Field(
        default=None,
        description="Optional custom question for the CrewAI workflow.",
    )


class WorkflowResponse(BaseModel):
    source: str
    topics: List[str]
    topic_count: int
    question: str
    workflow_roles: List[str]
    execution_mode: str = Field(
        description="`crewai` when real CrewAI ran, `fallback` when deterministic report is used."
    )
    report: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WorkflowBlueprintResponse(BaseModel):
    workflow_name: str
    process: str
    roles: List[str]
    description: str
