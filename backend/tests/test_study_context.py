from datetime import UTC, datetime

from app.models import Assessment, Resource
from app.services.study_context import relevant_coursework, study_guidance


def test_relevant_coursework_prefers_matching_resource_titles() -> None:
    assessment = Assessment(
        title="Circuits Quiz",
        assessment_type="quiz",
        description="Ideal ammeters and voltmeters",
        first_seen_at=datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
    )
    matching = Resource(
        title="Ideal ammeters and voltmeters notes",
        resource_type="PDF",
        first_seen_at=datetime.now(UTC),
    )
    unrelated = Resource(
        title="Course introduction",
        resource_type="PAGE",
        first_seen_at=datetime.now(UTC),
    )

    matching.url = "https://learn.uwaterloo.ca/d2l/api/le/1.82/1292783/content/topics/6611171/file"

    result = relevant_coursework(assessment, [unrelated, matching])

    assert result[0]["title"] == matching.title
    assert "ammeters" in result[0]["match_reason"]
    # Links open the LEARN page for the file rather than downloading it.
    assert result[0]["url"] == (
        "https://learn.uwaterloo.ca/d2l/le/content/1292783/viewContent/6611171/View"
    )


def test_study_guidance_is_assessment_type_specific() -> None:
    assessment = Assessment(title="Lab 2", assessment_type="lab")

    result = study_guidance(assessment)

    assert any("submission" in step.lower() for step in result)
