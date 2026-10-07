from pathlib import Path
from types import SimpleNamespace

from app.config import Settings
from app.services.vision_pdf import VisionPdfTranscriber


def test_handwritten_pdf_is_sent_as_high_detail_file_input(tmp_path: Path) -> None:
    class FakeResponses:
        def __init__(self) -> None:
            self.call = None

        def create(self, **kwargs):
            self.call = kwargs
            return SimpleNamespace(output_text="Shear stress: tau = V / A")

    responses = FakeResponses()
    pdf_path = tmp_path / "handwritten-notes.pdf"
    pdf_path.write_bytes(b"fake-pdf")
    transcriber = VisionPdfTranscriber(
        Settings(openai_api_key="test-key"),
        client=SimpleNamespace(responses=responses),
    )

    sidecar = transcriber.transcribe_to_sidecar(pdf_path, "SYDE 252 notes")

    assert sidecar == tmp_path / "handwritten-notes.txt"
    assert "Shear stress" in sidecar.read_text(encoding="utf-8")
    request = responses.call
    assert request["input"][0]["content"][0]["type"] == "input_file"
    assert request["input"][0]["content"][0]["detail"] == "high"
    assert request["input"][0]["content"][1]["type"] == "input_text"
