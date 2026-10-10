from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=2, max_length=4000)
    course_code: str | None = Field(default=None, max_length=100)
    # Skip the saved answer and ask the model again.
    fresh: bool = False
    # Continue this conversation; without it a new one is started.
    session_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")


class ChatCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str
    file_id: str | None = None
    kind: Literal["file", "web"] = "file"
    # The item's name on LEARN (course files) or the page title (web).
    title: str | None = None
    # Where to open it: the LEARN page for a course file, the page for a web source.
    url: str | None = None


class PlotSeries(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = ""
    # [x, y] pairs; a null y breaks the line (a jump or an undefined value).
    points: list[tuple[float, float | None]]
    style: Literal["line", "points"] = "line"
    fill: bool = False
    legend: bool = True


class PlotMarker(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float
    # Without y the marker is a vertical reference line at x.
    y: float | None = None
    label: str = ""


class PlotFigure(BaseModel):
    """A graph whose points were computed by the server from the tutor's formulas."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["plot"] = "plot"
    title: str = ""
    x_label: str = ""
    y_label: str = ""
    x_min: float
    x_max: float
    y_min: float | None = None
    y_max: float | None = None
    series: list[PlotSeries]
    markers: list[PlotMarker] = Field(default_factory=list)


class DiagramFigure(BaseModel):
    """A Mermaid flowchart or mind map showing how concepts connect."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["diagram"] = "diagram"
    source: str


class SketchFigure(BaseModel):
    """A sanitized SVG drawing: a free-body diagram, circuit or any course sketch."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["sketch"] = "sketch"
    title: str = ""
    svg: str


class SourceFigure(BaseModel):
    """A course question as it appears in the student's own file, and where to find it."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["source"] = "source"
    # The document's name on LEARN, and the saved file's name.
    title: str
    filename: str
    # The question's label, with its part: "Problem 2.6 (a)".
    question: str = ""
    # "p. 10 (PDF page 18)" or "slide 13"; empty when the page is not known.
    location: str = ""
    # "Chapter 2: Gathering Data", for a book with a table of contents.
    chapter: str = ""
    # The file's page on LEARN.
    url: str | None = None
    # Screenshots of the question from the local PDF, in reading order.
    images: list[str] = Field(default_factory=list)
    # The label was not found on the cited page, so the whole page is shown.
    whole_page: bool = False


ChatFigure = Annotated[
    PlotFigure | DiagramFigure | SketchFigure | SourceFigure, Field(discriminator="kind")
]


class ChatUsage(BaseModel):
    """Tokens one answer cost, so the student can see what caching and retrieval save."""

    model_config = ConfigDict(extra="forbid")

    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    citations: list[ChatCitation] = Field(default_factory=list)
    # Answers mark each figure's place with a ```figure block holding its index here.
    figures: list[ChatFigure] = Field(default_factory=list)
    usage: ChatUsage | None = None
    # True when this is a saved answer to the same question; it cost no tokens.
    cached: bool = False
    # The conversation this answer belongs to; send it back to ask a follow-up.
    session_id: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _drop_retired_fields(cls, value: object) -> object:
        # Saved conversations may hold "source_pages" (whole pages shown above an
        # answer); source figures replaced it.
        if isinstance(value, dict) and "source_pages" in value:
            return {key: item for key, item in value.items() if key != "source_pages"}
        return value
