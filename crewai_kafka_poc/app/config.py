from functools import lru_cache
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "CrewAI Kafka Topic PoC"
    app_env: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8001

    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_client_timeout_seconds: int = 5
    kafka_allow_mock_fallback: bool = True
    mock_topics_csv: str = (
        "orders.created,orders.updated,payments.received,"
        "inventory.adjusted,customer.notifications"
    )

    crewai_enabled: bool = True
    default_workflow_question: str = (
        "Create a short operational summary and identify potential high-risk topics."
    )
    openai_model_name: str = Field(default="gpt-4o-mini")

    @property
    def mock_topics(self) -> List[str]:
        return sorted(
            topic.strip()
            for topic in self.mock_topics_csv.split(",")
            if topic.strip()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
