"""Final exam times from the University of Waterloo's Final Examination Schedule site.

The site lists every course's exam in one table (Exam, Sections, Day, Date, Start, Finish,
Locations) once you are signed in, which the sync's browser does through UWaterloo's
single sign-on, the same way it is signed in to LEARN.
"""

import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, TypeAdapter

from app.schemas.extraction import AssessmentExtraction

SCHEDULE_URL = "https://uwaterloo.ca/final-examination-schedule/"
# Following this signs the browser in through single sign-on; no password is typed.
SIGN_IN_URL = f"{SCHEDULE_URL}saml_login"
_SOURCE = TypeAdapter(AnyHttpUrl).validate_python(SCHEDULE_URL)

_COURSE = re.compile(r"[A-Z]{2,8} \d{3}[A-Z]{0,2}")
_FINAL_TITLE = re.compile(r"\bfinal\b", re.IGNORECASE)
_EXAM_WORD = re.compile(r"\bexam", re.IGNORECASE)


class FinalExam(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course: str
    sections: str
    starts_at: datetime
    ends_at: datetime | None = None
    location: str = ""

    def describe(self, timezone_name: str) -> str:
        tz = ZoneInfo(timezone_name)
        start = self.starts_at.astimezone(tz)
        when = f"{start:%A, %B} {start.day}, {_clock(start)}"
        if self.ends_at is not None:
            when += f" to {_clock(self.ends_at.astimezone(tz))}"
        room = self.location if self.location and self.location != "TBA" else "room TBA"
        return f"Final exam schedule: {when}, {room} (sections {self.sections})"


def _clock(moment: datetime) -> str:
    return f"{moment:%I:%M %p}".lstrip("0")


def parse_schedule(text: str, timezone_name: str) -> dict[str, FinalExam]:
    """Each course's final from the schedule page's text, by course code ("SYDE 252").

    Rows without a date ("See instructor for exam details") are left out. A course listed
    more than once (different sections) keeps its first row.
    """

    tz = ZoneInfo(timezone_name)
    exams: dict[str, FinalExam] = {}
    for line in text.splitlines():
        cells = [" ".join(cell.replace("\xa0", " ").split()) for cell in line.split("\t")]
        if len(cells) < 7 or not _COURSE.fullmatch(cells[0]):
            continue
        course, sections, _day, date, start, finish, location = cells[:7]
        if course in exams or not date or not start:
            continue
        try:
            starts_at = datetime.strptime(f"{date} {start}", "%B %d, %Y %I:%M %p")
        except ValueError:
            continue
        try:
            ends_at: datetime | None = datetime.strptime(f"{date} {finish}", "%B %d, %Y %I:%M %p")
        except ValueError:
            ends_at = None
        exams[course] = FinalExam(
            course=course,
            sections=sections,
            starts_at=starts_at.replace(tzinfo=tz).astimezone(UTC),
            ends_at=ends_at.replace(tzinfo=tz).astimezone(UTC) if ends_at else None,
            location=location,
        )
    return exams


def apply_final_exam(
    assessments: list[AssessmentExtraction], exam: FinalExam | None, timezone_name: str
) -> list[AssessmentExtraction]:
    """Date the course's final from the schedule.

    The Outline usually lists the final with no date ("Final exam", "Final Exam" or just
    "Final"); that row gets the date, so it stays one deadline. Without one, a "Final exam"
    is added.
    """

    if exam is None:
        return assessments
    description = exam.describe(timezone_name)
    finals = [
        item
        for item in assessments
        # "Final exam", "Final Examination" or just "Final"; not a "Final Report", which
        # Study Agent also files under exams.
        if _FINAL_TITLE.search(item.title)
        and (_EXAM_WORD.search(item.title) or item.title.strip().casefold() == "final")
    ]
    for item in finals:
        item.due_at = exam.starts_at
        item.description = description
        item.source_url = _SOURCE
    if not finals:
        assessments.append(
            AssessmentExtraction(
                title="Final exam",
                assessment_type="exam",
                due_at=exam.starts_at,
                description=description,
                source_url=_SOURCE,
            )
        )
    return assessments
