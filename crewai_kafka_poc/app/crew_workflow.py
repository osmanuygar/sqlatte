from __future__ import annotations

from collections import defaultdict
import os
from typing import Iterable, List

from .config import Settings

try:
    from crewai import Agent, Crew, Process, Task
except Exception:  # pragma: no cover - depends on optional runtime installation
    Agent = Crew = Process = Task = None  # type: ignore[misc,assignment]


class CrewAIKafkaWorkflow:
    """CrewAI workflow that converts topic lists into operational reports."""

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
            f"- CrewAI status: **fallback used** ({error})",
            "",
            "## Topics by domain",
        ]
        for domain, domain_topics in grouped.items():
            lines.append(f"- **{domain}**: {', '.join(domain_topics)}")

        lines.extend(
            [
                "",
                "## Suggested actions",
                "1. Define ownership for each topic domain.",
                "2. Add retention and DLQ policy checks to CI/CD.",
                "3. Track topic growth and partition skew in observability dashboards.",
            ]
        )
        return "\n".join(lines)

    def run(self, topics: List[str], question: str) -> str:
        if not self.settings.crewai_enabled:
            return self._fallback_report(
                topics=topics,
                question=question,
                error="CREWAI_ENABLED is false",
            )

        if any(item is None for item in (Agent, Crew, Process, Task)):
            return self._fallback_report(
                topics=topics,
                question=question,
                error="crewai package not available",
            )

        if not os.getenv("OPENAI_API_KEY"):
            return self._fallback_report(
                topics=topics,
                question=question,
                error="OPENAI_API_KEY is not configured",
            )

        topic_list_markdown = "\n".join(f"- {topic}" for topic in topics) or "- (no topics)"

        try:
            discover_agent = Agent(
                role="Kafka Platform Analyst",
                goal="Analyze Kafka topics and infer domain ownership and risk signals.",
                backstory=(
                    "You are a platform engineer documenting event-driven architecture "
                    "for internal teams."
                ),
                allow_delegation=False,
                verbose=False,
            )

            report_agent = Agent(
                role="Automation Report Writer",
                goal="Produce concise technical reports for engineering teams.",
                backstory="You convert raw platform data into practical action items.",
                allow_delegation=False,
                verbose=False,
            )

            discover_task = Task(
                description=(
                    "Given this Kafka topic list:\n{topic_list_markdown}\n\n"
                    "Analyze naming conventions, probable domains, and risk hotspots. "
                    "Highlight unusual or potentially overloaded patterns."
                ),
                expected_output=(
                    "A structured bullet list with: domains, suspicious patterns, "
                    "and operational recommendations."
                ),
                agent=discover_agent,
            )

            report_task = Task(
                description=(
                    "Use the previous analysis to answer this question:\n{question}\n\n"
                    "Create a markdown report with these sections: "
                    "Summary, Domain Mapping, Risks, and Next Steps."
                ),
                expected_output="A concise markdown report for developers and platform teams.",
                agent=report_agent,
            )

            crew = Crew(
                agents=[discover_agent, report_agent],
                tasks=[discover_task, report_task],
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
                return output.strip()
            return self._fallback_report(
                topics=topics,
                question=question,
                error="CrewAI returned empty output",
            )
        except Exception as exc:
            return self._fallback_report(
                topics=topics,
                question=question,
                error=f"CrewAI execution failed: {exc}",
            )
