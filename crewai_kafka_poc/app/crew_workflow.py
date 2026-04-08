from __future__ import annotations

from collections import defaultdict
import os
from typing import Iterable, List, TypedDict

from .config import Settings

try:
    from crewai import Agent, Crew, Process, Task
except Exception:  # pragma: no cover - depends on optional runtime installation
    Agent = Crew = Process = Task = None  # type: ignore[misc,assignment]


class WorkflowRunResult(TypedDict):
    report: str
    execution_mode: str


class CrewAIKafkaWorkflow:
    """CrewAI workflow that converts topic lists into operational reports."""

    WORKFLOW_ROLES: List[str] = ["Solution Architect", "Coder", "Tester"]

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def _classify_topics(topics: Iterable[str]) -> dict[str, List[str]]:
        buckets: dict[str, List[str]] = defaultdict(list)
        for topic in topics:
            prefix = topic.split(".", 1)[0] if "." in topic else topic.split("_", 1)[0]
            buckets[prefix].append(topic)
        return dict(sorted(buckets.items(), key=lambda item: item[0]))

    def _fallback_report(self, topics: List[str], question: str, error: str) -> str:
        grouped = self._classify_topics(topics)
        lines = [
            "# Kafka Topic Automation Report (Fallback Mode)",
            "",
            f"- Total topics: **{len(topics)}**",
            f"- Workflow question: **{question}**",
            f"- Workflow roles: **{' -> '.join(self.WORKFLOW_ROLES)}**",
            f"- CrewAI status: **fallback used** ({error})",
            "",
            "## Topics by domain",
        ]
        for domain, domain_topics in grouped.items():
            lines.append(f"- **{domain}**: {', '.join(domain_topics)}")

        lines.extend(
            [
                "",
                "## Role output snapshots",
                "### 1) Solution Architect",
                "- Proposed architecture: FastAPI endpoint -> Kafka discovery service -> CrewAI sequential pipeline.",
                "- Inputs: Kafka topic list + teammate question.",
                "- Constraints: Must run even without Kafka/LLM in demo mode.",
                "",
                "### 2) Coder",
                "- Implementation focus: typed API contracts, fallback-safe service layer, and deterministic outputs.",
                "- Suggested code artifact: `workflow.py` orchestrator with role-tagged tasks.",
                "",
                "### 3) Tester",
                "- Validate `/api/topics` returns mock data if Kafka is unavailable.",
                "- Validate `/api/workflows/topic-report` returns markdown with role sections.",
                "- Validate no unhandled exception when LLM credentials are missing.",
                "",
                "## Suggested actions",
                "1. Define ownership for each topic domain.",
                "2. Add retention and DLQ policy checks to CI/CD.",
                "3. Track topic growth and partition skew in observability dashboards.",
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _has_any_llm_key() -> bool:
        return any(
            os.getenv(key)
            for key in (
                "ANTHROPIC_API_KEY",
                "OPENAI_API_KEY",
                "GEMINI_API_KEY",
                "GOOGLE_API_KEY",
            )
        )

    def get_workflow_blueprint(self) -> dict[str, object]:
        return {
            "process": "sequential",
            "roles": self.WORKFLOW_ROLES,
            "llm_model": self.settings.crewai_llm_model,
            "notes": [
                "Solution Architect designs the automation plan from Kafka topics.",
                "Coder turns the plan into implementation steps and pseudo code.",
                "Tester validates risks, edge cases, and test checks.",
            ],
        }

    def run(self, topics: List[str], question: str) -> WorkflowRunResult:
        if not self.settings.crewai_enabled:
            return {
                "report": self._fallback_report(
                    topics=topics,
                    question=question,
                    error="CREWAI_ENABLED is false",
                ),
                "execution_mode": "fallback",
            }

        if any(item is None for item in (Agent, Crew, Process, Task)):
            return {
                "report": self._fallback_report(
                    topics=topics,
                    question=question,
                    error="crewai package not available",
                ),
                "execution_mode": "fallback",
            }

        if not self._has_any_llm_key():
            return {
                "report": self._fallback_report(
                    topics=topics,
                    question=question,
                    error=(
                        "No LLM API key configured. Set ANTHROPIC_API_KEY (recommended for Claude), "
                        "or OPENAI_API_KEY, or GEMINI/GOOGLE API key."
                    ),
                ),
                "execution_mode": "fallback",
            }

        topic_list_markdown = "\n".join(f"- {topic}" for topic in topics) or "- (no topics)"

        try:
            architect_agent = Agent(
                role="Solution Architect",
                goal=(
                    "Design the best workflow architecture for Kafka topic automation "
                    "with clear ownership, observability, and governance."
                ),
                backstory=(
                    "You are a senior solution architect creating practical, scalable "
                    "automation blueprints for engineering teams."
                ),
                allow_delegation=False,
                verbose=False,
                llm=self.settings.crewai_llm_model,
            )

            coder_agent = Agent(
                role="Coder",
                goal=(
                    "Convert architecture decisions into implementation steps, endpoint contracts, "
                    "and maintainable pseudo code."
                ),
                backstory=(
                    "You are a backend engineer who builds FastAPI and workflow automation "
                    "PoCs for team adoption."
                ),
                allow_delegation=False,
                verbose=False,
                llm=self.settings.crewai_llm_model,
            )

            tester_agent = Agent(
                role="Tester",
                goal=(
                    "Review implementation strategy and define concrete test cases, "
                    "risk checks, and quality gates."
                ),
                backstory=(
                    "You are a QA engineer focused on API reliability, fallback behavior, "
                    "and production-readiness checks."
                ),
                allow_delegation=False,
                verbose=False,
                llm=self.settings.crewai_llm_model,
            )

            architect_task = Task(
                description=(
                    "You are the Solution Architect.\n"
                    "Given this Kafka topic list:\n{topic_list_markdown}\n\n"
                    "And this stakeholder question:\n{question}\n\n"
                    "Design the automation workflow and architecture. Include:\n"
                    "1) Domain mapping by topic naming patterns\n"
                    "2) Data flow design (FastAPI -> Kafka service -> CrewAI)\n"
                    "3) Governance and observability recommendations\n"
                    "4) Risks and assumptions."
                ),
                expected_output=(
                    "A markdown section titled 'Solution Architect Plan' with architecture, "
                    "decisions, and rationale."
                ),
                agent=architect_agent,
            )

            coder_task = Task(
                description=(
                    "You are the Coder.\n"
                    "Use the architect output and produce implementation-ready details.\n"
                    "Include:\n"
                    "1) API endpoint contracts\n"
                    "2) Suggested Python module boundaries\n"
                    "3) Pseudo code snippets for workflow orchestration\n"
                    "4) Error handling and fallback strategy."
                ),
                expected_output=(
                    "A markdown section titled 'Coder Implementation Plan' with code-focused "
                    "deliverables."
                ),
                agent=coder_agent,
            )

            tester_task = Task(
                description=(
                    "You are the Tester.\n"
                    "Based on architect and coder outputs, produce a QA test strategy.\n"
                    "Include:\n"
                    "1) Functional test cases\n"
                    "2) Failure mode tests (Kafka down, missing API key)\n"
                    "3) Non-functional checks (latency, reliability)\n"
                    "4) Release gate checklist.\n"
                    "End with a concise final summary for teammates."
                ),
                expected_output=(
                    "A markdown section titled 'Tester Validation Plan' and a final "
                    "'Team Summary' section."
                ),
                agent=tester_agent,
            )

            crew = Crew(
                agents=[architect_agent, coder_agent, tester_agent],
                tasks=[architect_task, coder_task, tester_task],
                process=Process.sequential,
                verbose=False,
            )

            result = crew.kickoff(
                inputs={
                    "topic_list_markdown": topic_list_markdown,
                    "question": question,
                }
            )
            output = getattr(result, "raw", str(result))
            if isinstance(output, str) and output.strip():
                return {"report": output.strip(), "execution_mode": "crewai"}
            return {
                "report": self._fallback_report(
                    topics=topics,
                    question=question,
                    error="CrewAI returned empty output",
                ),
                "execution_mode": "fallback",
            }
        except Exception as exc:
            return {
                "report": self._fallback_report(
                    topics=topics,
                    question=question,
                    error=f"CrewAI execution failed: {exc}",
                ),
                "execution_mode": "fallback",
            }
