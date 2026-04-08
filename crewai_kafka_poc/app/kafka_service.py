from __future__ import annotations

from typing import List, Optional

from .config import Settings
from .models import TopicListResponse

try:
    from kafka.admin import KafkaAdminClient
except Exception:  # pragma: no cover - import availability depends on runtime env
    KafkaAdminClient = None  # type: ignore[misc,assignment]


class KafkaTopicService:
    """Fetches Kafka topics with optional mock fallback."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _list_real_topics(self) -> List[str]:
        if KafkaAdminClient is None:
            raise RuntimeError(
                "kafka-python is not installed. Install dependencies to query Kafka."
            )

        client: Optional[KafkaAdminClient] = None
        try:
            timeout_ms = self.settings.kafka_client_timeout_seconds * 1000
            client = KafkaAdminClient(
                bootstrap_servers=self.settings.kafka_bootstrap_servers,
                request_timeout_ms=timeout_ms,
                api_version_auto_timeout_ms=timeout_ms,
                client_id="crewai-kafka-poc",
            )
            topics = sorted(
                topic
                for topic in client.list_topics()
                if topic and not topic.startswith("__")
            )
            return topics
        finally:
            if client is not None:
                client.close()

    def list_topics(self) -> TopicListResponse:
        try:
            topics = self._list_real_topics()
            return TopicListResponse(
                source="kafka",
                topics=topics,
                topic_count=len(topics),
            )
        except Exception as exc:
            if not self.settings.kafka_allow_mock_fallback:
                raise

            mock_topics = self.settings.mock_topics
            return TopicListResponse(
                source="mock",
                topics=mock_topics,
                topic_count=len(mock_topics),
                error=str(exc),
            )
