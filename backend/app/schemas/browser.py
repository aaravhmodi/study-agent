from pydantic import BaseModel, ConfigDict, Field


class PageLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = ""
    href: str


class BrowserPageSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    title: str | None = None
    text: str = Field(default="", max_length=100_000)
    links: list[PageLink] = Field(default_factory=list)


class BrowserDownloadedResource(BaseModel):
    """A read-only resource fetched inside the authenticated browser session."""

    model_config = ConfigDict(extra="forbid")

    url: str
    resolved_url: str | None = None
    filename: str
    content_type: str = "application/octet-stream"
    content_base64: str
    skipped: bool = False
    skip_reason: str | None = None
