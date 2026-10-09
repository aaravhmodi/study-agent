from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str | None = None
    openai_model: str = "gpt-6-astra"
    # Course Q&A runs on OpenAI's cost-tier model with a small retrieval and
    # output budget; vision transcription keeps the stronger openai_model.
    openai_chat_model: str = "gpt-6-luna"
    openai_chat_reasoning_effort: str = Field(
        default="low", pattern="^(none|low|medium|high|xhigh|max)$"
    )
    rag_max_results: int = Field(default=6, ge=1, le=50)
    rag_max_output_tokens: int = Field(default=2500, ge=256, le=32000)
    browser_mode: str = Field(default="local", pattern="^(local|cloud|mock)$")
    database_url: str = "sqlite:///./data/study_agent.db"
    learn_url: str = "https://learn.uwaterloo.ca"
    browser_use_api_key: str | None = None
    browser_use_executable: str = "browser-use"
    timezone: str = "America/Toronto"

    @property
    def project_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    @property
    def data_dir(self) -> Path:
        return self.project_root / "data"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
