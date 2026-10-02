import json
from pathlib import Path

from app.schemas.course import CourseDiscoveryResult
from app.schemas.extraction import CourseScanResult

FIXTURES = Path(__file__).parents[2] / "tests" / "fixtures" / "learn"


def test_course_fixture_validates() -> None:
    payload = json.loads((FIXTURES / "courses.json").read_text(encoding="utf-8"))
    result = CourseDiscoveryResult.model_validate(payload)
    assert len(result.courses) == 2
    assert result.courses[0].code == "ECON 101"


def test_course_scan_fixture_validates() -> None:
    payload = json.loads((FIXTURES / "physics.json").read_text(encoding="utf-8"))
    result = CourseScanResult.model_validate(payload)
    assert result.course_name == "Physics 111"


def test_malformed_browser_output_is_rejected() -> None:
    payload = {"courses": [{"name": "Missing URL"}]}
    try:
        CourseDiscoveryResult.model_validate(payload)
    except ValueError:
        pass
    else:
        raise AssertionError("malformed browser output unexpectedly validated")
