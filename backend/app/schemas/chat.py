from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=2, max_length=4000)
    course_code: str | None = Field(default=None, max_length=100)
    # Skip the saved answer and ask the model again.
    fresh: bool = False


class ChatCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str
    file_id: str | None = None
    # Set for online sources; course files have only a filename.
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


ChatFigure = Annotated[PlotFigure | DiagramFigure | SketchFigure, Field(discriminator="kind")]


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
