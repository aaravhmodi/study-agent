import base64
import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from app import main
from app.config import Settings
from app.schemas.chat import ChatResponse, TurnImage
from app.services.chat_images import (
    MODEL_SIDE,
    THUMBNAIL_SIDE,
    ImageError,
    Picture,
    prepare_picture,
)
from app.services.chat_sessions import ChatSessionStore
from app.services.rag import PICTURE_PROMPT, RagService
from fastapi.testclient import TestClient
from PIL import Image

from tests.fake_openai import FakeVectorStores


def _data_url(image: Image.Image, kind: str = "PNG") -> str:
    buffer = BytesIO()
    image.save(buffer, kind)
    return f"data:image/{kind.lower()};base64,{base64.b64encode(buffer.getvalue()).decode()}"


def _opened(data_url: str) -> Image.Image:
    return Image.open(BytesIO(base64.b64decode(data_url.split(",", 1)[1])))


SCREENSHOT = _data_url(Image.new("RGB", (640, 400), "navy"))


def test_a_picture_is_redrawn_for_the_model_and_given_a_thumbnail() -> None:
    picture = prepare_picture(SCREENSHOT)

    sent, thumbnail = _opened(picture.data_url), _opened(picture.thumbnail)
    assert (sent.format, sent.size) == ("PNG", (640, 400))
    assert thumbnail.format == "JPEG" and max(thumbnail.size) == THUMBNAIL_SIDE
    assert picture.text == ""


def test_a_large_photo_is_shrunk_and_transparency_becomes_white() -> None:
    photo = prepare_picture(_data_url(Image.new("RGB", (4000, 3000), "gray"), "JPEG"))
    assert _opened(photo.data_url).size == (MODEL_SIDE, MODEL_SIDE * 3 // 4)

    cutout = prepare_picture(_data_url(Image.new("RGBA", (20, 20), (255, 0, 0, 0))))
    assert _opened(cutout.data_url).convert("RGB").getpixel((10, 10)) == (255, 255, 255)


def test_only_real_images_are_accepted() -> None:
    not_an_image = base64.b64encode(b"<svg onload=alert(1)>").decode()
    for attachment in (
        "",
        "hello",
        f"data:image/svg+xml;base64,{not_an_image}",
        f"data:image/png;base64,{not_an_image}",
        f"data:text/html;base64,{not_an_image}",
        "data:image/png;base64,!!!not-base64!!!",
    ):
        with pytest.raises(ImageError):
            prepare_picture(attachment)


class Responses:
    """Records each model call and answers with fixed text."""

    def __init__(self, text: str = "## Overview\nA beam.") -> None:
        self.calls: list[dict[str, Any]] = []
        self.text = text

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(output_text=self.text, model_dump=lambda: {"output": []})


def _tutor(tmp_path: Path, responses: Responses) -> tuple[RagService, FakeVectorStores]:
    stores = FakeVectorStores()
    service = RagService(
        Settings(_env_file=None, openai_api_key="test-key"),
        client=SimpleNamespace(responses=responses, vector_stores=stores),  # type: ignore[arg-type]
    )
    service.manifest_path = tmp_path / "manifest.json"
    service.manifest_path.write_text(
        json.dumps({"vector_store_id": "vs-test", "files": {"r1": {"course_code": "SYDE 286"}}}),
        encoding="utf-8",
    )
    return service, stores


def test_a_picture_is_read_once_so_its_content_outlives_the_turn(tmp_path: Path) -> None:
    responses = Responses("Problem 3. A beam of length \\(L = 4\\) m carries 12 kN.")
    service, _stores = _tutor(tmp_path, responses)

    picture = service.read_picture(prepare_picture(SCREENSHOT))

    assert picture.text.startswith("Problem 3. A beam of length")
    (call,) = responses.calls
    # The stronger vision model reads it, and is told to transcribe, not to solve.
    assert call["model"] == Settings(_env_file=None).openai_model
    text, image = call["input"][0]["content"]
    assert text == {"type": "input_text", "text": PICTURE_PROMPT}
    assert image["type"] == "input_image" and image["image_url"].startswith("data:image/png")


def test_a_picture_that_cannot_be_read_is_still_shown_to_the_tutor(tmp_path: Path) -> None:
    class Failing(Responses):
        def create(self, **kwargs: Any) -> SimpleNamespace:
            raise TimeoutError("vision call timed out")

    service, _stores = _tutor(tmp_path, Failing())
    prepared = prepare_picture(SCREENSHOT)

    assert service.read_picture(prepared) == prepared


def test_the_tutor_sees_the_picture_and_searches_by_what_it_says(tmp_path: Path) -> None:
    responses = Responses()
    service, stores = _tutor(tmp_path, responses)
    picture = prepare_picture(SCREENSHOT).model_copy(
        update={"text": "Problem 3. Find the shear force at midspan."}
    )

    service.ask("Explain this", "SYDE 286", pictures=[picture])
    service.ask("Explain this", "SYDE 286", pictures=[picture])

    # The course files are searched for the problem, not for "explain this".
    assert "Find the shear force at midspan." in stores.calls[0]["query"]
    (message,) = responses.calls[0]["input"]
    text, image = message["content"]
    assert "Attached picture 1, as read:\nProblem 3. Find the shear force" in text["text"]
    assert image == {"type": "input_image", "image_url": picture.data_url}
    # The same words about a different picture are a different question: no saved answer.
    assert len(responses.calls) == 2


def test_a_follow_up_goes_on_what_an_earlier_picture_said(tmp_path: Path) -> None:
    responses = Responses()
    service, _stores = _tutor(tmp_path, responses)
    store = ChatSessionStore(tmp_path / "sessions.json")
    session = store.create("Explain this", "SYDE 286")
    kept = TurnImage(thumbnail="data:image/jpeg;base64,AAAA", text="Problem 3. A 12 kN load.")
    session = store.add_turn(
        session.id, "Explain this", "SYDE 286", ChatResponse(answer="It is a beam."), images=[kept]
    )

    service.ask("Why is the reaction half the load?", "SYDE 286", history=session.turns)

    sent = responses.calls[0]["input"]
    # No picture is sent again, only what it said.
    assert isinstance(sent, str)
    assert "(attached a picture, which read: Problem 3. A 12 kN load.)" in sent
    # And the thumbnail and text are what the saved conversation holds.
    reloaded = store.get(session.id)
    assert reloaded is not None and reloaded.turns[0].images == [kept]


class FakeTutor:
    """Stands in for RagService in the chat endpoint."""

    seen: list[list[Picture]] = []

    def __init__(self, settings: Settings) -> None:
        pass

    def read_picture(self, picture: Picture) -> Picture:
        return picture.model_copy(update={"text": "Problem 3. A beam."})

    def ask(self, question: str, course_code: str | None = None, **kwargs: Any) -> ChatResponse:
        FakeTutor.seen.append(kwargs["pictures"])
        return ChatResponse(answer="It is a beam.")


def test_the_chat_keeps_a_thumbnail_and_the_text_of_each_picture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    FakeTutor.seen = []
    monkeypatch.setattr(main, "RagService", FakeTutor)
    monkeypatch.setattr(main, "get_settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr(main, "_sessions_path", lambda: tmp_path / "sessions.json")
    client = TestClient(main.app)

    answered = client.post(
        "/chat", json={"question": "Explain this", "images": [{"data_url": SCREENSHOT}]}
    )

    assert answered.status_code == 200
    # The reply says what was read, so the page can show it straight away.
    assert [image["text"] for image in answered.json()["images"]] == ["Problem 3. A beam."]
    (pictures,) = FakeTutor.seen
    assert pictures[0].text == "Problem 3. A beam."
    saved = client.get(f"/chat/sessions/{answered.json()['session_id']}").json()
    (image,) = saved["turns"][0]["images"]
    assert image["text"] == "Problem 3. A beam."
    # A small JPEG, not the screenshot itself.
    assert image["thumbnail"].startswith("data:image/jpeg;base64,")
    assert len(image["thumbnail"]) < len(SCREENSHOT) * 4

    refused = client.post(
        "/chat", json={"question": "Explain this", "images": [{"data_url": "x" * 40}]}
    )
    assert refused.status_code == 422 and "Attached image" in refused.json()["detail"]
    too_many = client.post(
        "/chat", json={"question": "Explain this", "images": [{"data_url": SCREENSHOT}] * 5}
    )
    assert too_many.status_code == 422
