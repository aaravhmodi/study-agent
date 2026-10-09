from typing import Annotated, Literal

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


ChatFigure = Annotated[PlotFigure | DiagramFigure, Field(discriminator="kind")]


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    citations: list[ChatCitation] = Field(default_factory=list)
    # Answers mark each figure's place with a ```figure block holding its index here.
    figures: list[ChatFigure] = Field(default_factory=list)
