"""Pictures a student attaches to a question: checked, shrunk, and given a thumbnail.

A picture arrives from the page as a data URL. Nothing about it is trusted: it must
be a real image of a sensible size, and it is drawn again from its pixels, which drops
whatever else the file carried. The model gets the redrawn picture; the conversation
keeps only a small thumbnail and what the picture was read as saying.
"""

import base64
import binascii
import re
from io import BytesIO

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict

MAX_IMAGES = 4
# What the page may send for one picture, as base64 text.
MAX_DATA_URL_CHARS = 6_000_000
MAX_PIXELS = 40_000_000
# The longest side sent to the model, and kept as the thumbnail.
MODEL_SIDE = 1600
THUMBNAIL_SIDE = 320

_DATA_URL = re.compile(r"^data:image/(png|jpeg|jpg|webp|gif);base64,([A-Za-z0-9+/=\s]+)$")


class ImageError(ValueError):
    """The attachment is not a picture the tutor can use."""


class Picture(BaseModel):
    """An attached picture, ready for the model and for the conversation."""

    model_config = ConfigDict(extra="forbid")

    # A PNG of at most MODEL_SIDE pixels a side, for the model to look at.
    data_url: str
    # A small JPEG to show beside the question later.
    thumbnail: str
    # What the picture says, once it has been read.
    text: str = ""


def prepare_picture(data_url: str) -> Picture:
    """Check an attachment and redraw it, or raise ImageError."""

    match = _DATA_URL.match(data_url.strip())
    if not match or len(data_url) > MAX_DATA_URL_CHARS:
        raise ImageError("attach a PNG, JPEG, WebP or GIF image of a few megabytes at most")
    try:
        raw = base64.b64decode(match.group(2), validate=False)
        image = Image.open(BytesIO(raw))
        if image.width * image.height > MAX_PIXELS:
            raise ImageError("that image is too large")
        image.load()
    except (binascii.Error, UnidentifiedImageError, OSError, ValueError) as exc:
        if isinstance(exc, ImageError):
            raise
        raise ImageError("that file could not be read as an image") from exc
    # Flatten transparency onto white, as a screenshot would look on paper.
    rgba = image.convert("RGBA")
    flat = Image.new("RGB", rgba.size, "white")
    flat.paste(rgba, mask=rgba.getchannel("A"))
    return Picture(
        data_url=_encoded(flat, MODEL_SIDE, "PNG"),
        thumbnail=_encoded(flat, THUMBNAIL_SIDE, "JPEG"),
    )


def _encoded(image: Image.Image, side: int, kind: str) -> str:
    copy = image.copy()
    copy.thumbnail((side, side))
    buffer = BytesIO()
    if kind == "PNG":
        copy.save(buffer, "PNG", optimize=True)
    else:
        copy.save(buffer, "JPEG", quality=72)
    mime = "image/png" if kind == "PNG" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(buffer.getvalue()).decode('ascii')}"
