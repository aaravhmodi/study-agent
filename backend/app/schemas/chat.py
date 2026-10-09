from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=2, max_length=4000)
    course_code: str | None = Field(default=None, max_length=100)


class ChatCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str
    file_id: str | None = None
    # Set for online sources; course files have only a filename.
    url: str | None = None


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    citations: list[ChatCitation] = Field(default_factory=list)
