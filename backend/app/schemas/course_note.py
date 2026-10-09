from pydantic import BaseModel, ConfigDict, Field

from app.services.course_notes import MAX_NOTE_CHARS


class CourseNoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=MAX_NOTE_CHARS)
    # The assessment the note is about ("Midterm"), if any.
    about: str | None = Field(default=None, max_length=200)
