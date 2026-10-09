"""A stand-in for the OpenAI vector-store search used by the tutor."""

from types import SimpleNamespace
from typing import Any

LECTURE_7 = "Lecture_07_Shear_and_Moment.pdf"


def search_result(filename: str, text: str, score: float = 0.8, file_id: str = "") -> Any:
    return SimpleNamespace(
        filename=filename,
        file_id=file_id or f"file-{filename}",
        score=score,
        content=[SimpleNamespace(type="text", text=text)],
    )


class FakeVectorStores:
    """Records search calls and returns fixed results."""

    def __init__(self, results: list[Any] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.results = (
            results
            if results is not None
            else [
                search_result(LECTURE_7, "Shear force V is the internal transverse force."),
                search_result("Tutorial_04_Beams.pdf", "Draw V and M diagrams.", 0.7),
            ]
        )

    def search(self, vector_store_id: str, **kwargs: Any) -> Any:
        self.calls.append({"vector_store_id": vector_store_id, **kwargs})
        return SimpleNamespace(data=self.results)
