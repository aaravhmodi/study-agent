from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field


class CourseSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    code: str | None = None
    url: AnyHttpUrl
    term: str | None = None
    outline_url: AnyHttpUrl | None = None


class CourseDiscoveryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    courses: list[CourseSummary] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
