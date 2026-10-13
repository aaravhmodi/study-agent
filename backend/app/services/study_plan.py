"""Today's study plan: how long to spend on what.

Each piece of graded work gets an amount of preparation, spread evenly over the days
before it. For tests and quizzes that amount follows what practice shows: a course the
student is answering well gets half as long, one they are getting wrong gets half as much
again. The last two days before anything get more. If the day comes to more than the
student's limit, everything is scaled down together.

No model is involved: the same deadlines and the same answers always give the same plan.
"""

from datetime import datetime, timedelta
from math import ceil

from pydantic import BaseModel, ConfigDict, Field

# Kind of work: (hours of preparation in all, days before it that preparation starts).
PREPARATION: dict[str, tuple[float, int]] = {
    "exam": (15, 14),
    "test": (10, 10),
    "quiz": (2, 3),
    "assignment": (4, 5),
    "project": (8, 10),
    "lab": (2, 3),
    "other": (1, 2),
}
# Work that tests what you know, so practice results change how long it needs.
TESTED = frozenset({"exam", "test", "quiz"})
# Fewer answers than this say too little about a course to change its time. A daily
# check-up asks two questions of each course it covers, so one day's is enough to count;
# the week's answers then add to it.
MIN_EVIDENCE = 2
# With a day or two left, the usual share is not enough.
LAST_DAYS = 2
LAST_DAYS_PUSH = 1.5
MINUTES_PER_REVIEW_QUESTION = 1.5
SHORTEST_BLOCK = 10


class Work(BaseModel):
    """One piece of graded work still to come."""

    model_config = ConfigDict(extra="forbid")

    course: str
    title: str
    kind: str
    due_at: datetime


class Knowledge(BaseModel):
    """What the last week of practice shows for one course."""

    model_config = ConfigDict(extra="forbid")

    asked: int = 0
    right: int = 0
    # The topics of the questions last answered wrong, most missed first.
    weak_topics: list[str] = Field(default_factory=list)

    @property
    def score(self) -> float | None:
        return self.right / self.asked if self.asked >= MIN_EVIDENCE else None


class StudyBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course: str
    title: str
    kind: str
    minutes: int
    due_at: datetime
    days_left: int
    # Why this long, in a sentence the student can check.
    reason: str
    topics: list[str] = Field(default_factory=list)


class StudyPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # What to do today, soonest deadline first.
    blocks: list[StudyBlock] = Field(default_factory=list)
    # Practice questions due for another go, and the time they take.
    review_due: int = 0
    review_minutes: int = 0
    minutes: int = 0
    # What the day came to before it was cut to the limit; equal to minutes when it fit.
    wanted_minutes: int = 0
    limit_minutes: int = 0


def _round(minutes: float) -> int:
    return int(5 * round(minutes / 5))


def _days(count: int) -> str:
    return "tomorrow" if count == 1 else f"in {count} days"


def _block(work: Work, knowledge: Knowledge | None, now: datetime) -> StudyBlock | None:
    hours, window = PREPARATION.get(work.kind, PREPARATION["other"])
    remaining = work.due_at - now
    if remaining <= timedelta(0):
        return None
    days_left = max(1, ceil(remaining / timedelta(days=1)))
    if days_left > window:
        return None
    minutes = hours * 60 / window
    when = f"{work.title} is {_days(days_left)}."
    topics: list[str] = []
    if work.kind in TESTED:
        if knowledge is None or knowledge.score is None:
            reason = f"{when} No practice results yet, so the usual time; a check-up adjusts it."
        else:
            # Everything right halves the time; everything wrong adds half again.
            score = knowledge.score
            minutes *= 1.5 - score
            share = f"{knowledge.right} of {knowledge.asked} right in practice this week"
            verdict = "less" if score >= 0.7 else "more" if score < 0.5 else "the usual"
            reason = f"{when} {share}, so {verdict} time."
            topics = knowledge.weak_topics[:3]
    else:
        reason = f"{work.title} is due {_days(days_left)}."
    if days_left <= LAST_DAYS:
        minutes *= LAST_DAYS_PUSH
    return StudyBlock(
        course=work.course,
        title=work.title,
        kind=work.kind,
        minutes=max(SHORTEST_BLOCK, _round(minutes)),
        due_at=work.due_at,
        days_left=days_left,
        reason=reason,
        topics=topics,
    )


def make_plan(
    work: list[Work],
    knowledge: dict[str, Knowledge],
    review_due: int,
    now: datetime,
    limit_minutes: int,
) -> StudyPlan:
    blocks = [block for item in work if (block := _block(item, knowledge.get(item.course), now))]
    blocks.sort(key=lambda block: (block.due_at, -block.minutes, block.course))
    review = _round(review_due * MINUTES_PER_REVIEW_QUESTION) if review_due else 0
    if review_due:
        review = max(5, review)
    wanted = sum(block.minutes for block in blocks) + review
    if wanted > limit_minutes > 0:
        scale = limit_minutes / wanted
        for block in blocks:
            block.minutes = max(SHORTEST_BLOCK, _round(block.minutes * scale))
        review = max(5, _round(review * scale)) if review else 0
        # Rounding each block to five minutes can leave the day a little over.
        over = sum(block.minutes for block in blocks) + review - limit_minutes
        if over > 0 and blocks:
            longest = max(blocks, key=lambda block: block.minutes)
            longest.minutes = max(SHORTEST_BLOCK, longest.minutes - over)
    return StudyPlan(
        blocks=blocks,
        review_due=review_due,
        review_minutes=review,
        minutes=sum(block.minutes for block in blocks) + review,
        wanted_minutes=wanted,
        limit_minutes=limit_minutes,
    )
