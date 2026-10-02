from datetime import datetime

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field


class AssessmentExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    assessment_type: str = "other"
    due_at: datetime | None = None
    weight_percent: float | None = Field(default=None, ge=0, le=100)
    description: str | None = None
    source_url: AnyHttpUrl | None = None


class AnnouncementExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    body: str | None = None
    published_at: datetime | None = None
    source_url: AnyHttpUrl | None = None


class ResourceExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    resource_type: str = "OTHER"
    url: AnyHttpUrl | None = None
    uploaded_at: datetime | None = None


class TopicExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str | None = None
    importance: int = Field(default=1, ge=1, le=10)
    prerequisites: list[str] = Field(default_factory=list)


class CourseScanResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_name: str
    assessments: list[AssessmentExtraction] = Field(default_factory=list)
    announcements: list[AnnouncementExtraction] = Field(default_factory=list)
    resources: list[ResourceExtraction] = Field(default_factory=list)
    topics: list[TopicExtraction] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
