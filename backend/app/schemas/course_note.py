from pydantic import BaseModel, ConfigDict, Field

from app.services.course_notes import MAX_NOTE_CHARS


class CourseNoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # An empty note removes it.
    text: str = Field(max_length=MAX_NOTE_CHARS)
