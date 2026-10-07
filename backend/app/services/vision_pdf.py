"""Use OpenAI vision to transcribe handwritten PDFs for selected courses."""

import base64
from pathlib import Path

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings

_VISION_MARKER = "[OpenAI visual transcription]"


class VisionTranscription(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)


class VisionPdfTranscriber:
    def __init__(self, settings: Settings, client: OpenAI | None = None) -> None:
        if not settings.openai_api_key and client is None:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        self.client = client or OpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_model

    def transcribe_to_sidecar(self, pdf_path: Path, title: str) -> Path | None:
        sidecar = pdf_path.with_suffix(".txt")
        if sidecar.is_file() and sidecar.read_text(encoding="utf-8").startswith(_VISION_MARKER):
            return sidecar
        encoded = base64.b64encode(pdf_path.read_bytes()).decode("ascii")
        response = self.client.responses.create(
            model=self.model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_file",
                            "filename": pdf_path.name,
                            "file_data": f"data:application/pdf;base64,{encoded}",
                            "detail": "high",
                        },
                        {
                            "type": "input_text",
                            "text": (
                                "Transcribe this handwritten course PDF faithfully for search. "
                                "Preserve equations, symbols, definitions, labels, and page order. "
                                f"Course resource: {title}. Do not summarize or invent "
                                "unreadable text."
                            ),
                        },
                    ],
                }
            ],
        )
        result = VisionTranscription.model_validate(
            {"text": str(getattr(response, "output_text", "")).strip()}
        )
        sidecar.write_text(f"{_VISION_MARKER}\n{result.text}\n", encoding="utf-8")
        return sidecar
