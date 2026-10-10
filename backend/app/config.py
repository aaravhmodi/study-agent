from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_REAL_DATABASE_URL = "sqlite:///./data/study_agent.db"


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
    # Course text sent with each question; passages stop once this many tokens are used.
    rag_context_tokens: int = Field(default=3000, ge=300, le=20000)
    # Search results below this relevance score (0 to 1) are not sent.
    rag_min_score: float = Field(default=0.3, ge=0, le=1)
    rag_max_output_tokens: int = Field(default=3000, ge=256, le=32000)
    # Adds online context next to course materials; costs one search per question.
    rag_web_search: bool = True
    browser_mode: str = Field(default="local", pattern="^(local|cloud|mock)$")
    database_url: str = _REAL_DATABASE_URL
    learn_url: str = "https://learn.uwaterloo.ca"
    browser_use_api_key: str | None = None
    browser_use_executable: str = "browser-use"
    timezone: str = "America/Toronto"
    # Needed to serve the dashboard beyond this computer; every request then needs it.
    dashboard_password: str | None = Field(default=None, min_length=12)

    @field_validator("dashboard_password", mode="before")
    @classmethod
    def _blank_is_no_password(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def _keep_demo_data_separate(self) -> "Settings":
        # Mock mode syncs made-up courses under real course codes, so it must
        # never write to the real database, even when .env names it.
        if self.browser_mode == "mock" and self.database_url == _REAL_DATABASE_URL:
            self.database_url = "sqlite:///./data/demo.db"
        return self

    @property
    def project_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    @property
    def data_dir(self) -> Path:
        return self.project_root / "data"

    @property
    def downloads_dir(self) -> Path:
        name = "demo-downloads" if self.browser_mode == "mock" else "downloads"
        return self.data_dir / name


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
