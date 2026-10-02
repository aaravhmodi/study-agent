from pydantic import BaseModel, ConfigDict, Field


class BrowserTestResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    browser_connected: bool
    learn_reachable: bool
    url: str | None = None
    title: str | None = None
    message: str | None = None


class SyncSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    courses_found: int = Field(ge=0)
    assessments_found: int = Field(ge=0)
    resources_found: int = Field(ge=0)
    changes_found: int = Field(ge=0)
