"""Made-up LEARN pages for mock mode, so the app can be developed without Chrome.

Pages are keyed by the URLs the course agent visits. Due dates are relative to
today so the demo always has upcoming work.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

LEARN = "https://learn.uwaterloo.ca"


@dataclass(frozen=True)
class DemoCourse:
    code: str
    title: str
    offering_id: str
    # (title, days from today, hour) for each dated calendar item.
    due: list[tuple[str, int, int]] = field(default_factory=list)
    # (lecture title, notes) for each content item.
    lectures: list[tuple[str, str]] = field(default_factory=list)
    announcements: list[tuple[str, str]] = field(default_factory=list)


# Offering ids match the real Fall 2026 shells the course agent knows about.
DEMO_COURSES = [
    DemoCourse(
        "SYDE 212",
        "Probability, Statistics, and Data",
        "1299242",
        due=[("Assignment 4: Bayes problems", 5, 23)],
        lectures=[
            (
                "Lecture 01: Probability axioms",
                "A sample space S lists every outcome. Probabilities satisfy "
                "P(A) >= 0, P(S) = 1, and add for disjoint events.",
            ),
            (
                "Lecture 02: Conditional probability and Bayes' theorem",
                "Conditional probability P(A|B) = P(A and B) / P(B). Bayes' theorem "
                "reverses it: P(A|B) = P(B|A) P(A) / P(B). Worked example: a test "
                "with 95% sensitivity for a 1% prevalence condition.",
            ),
        ],
        announcements=[("Office hours moved", "Thursday office hours are in E5 2004.")],
    ),
    DemoCourse(
        "SYDE 252",
        "Linear Systems and Signals",
        "1318237",
        due=[("Homework 2: Convolution assignment", 1, 23), ("Midterm test", 14, 19)],
        lectures=[
            (
                "Lecture 01: Signal energy and power",
                "Signal energy E = integral of |x(t)|^2 dt. Power is the time "
                "average of |x(t)|^2. Doubling amplitude quadruples energy.",
            ),
            (
                "Lecture 03: Convolution",
                "The output of an LTI system is y(t) = x(t) * h(t), the "
                "convolution of the input with the impulse response.",
            ),
        ],
    ),
    DemoCourse(
        "SYDE 262",
        "Engineering Economics of Design",
        "1296387",
        due=[("Case study 1 project", 11, 17)],
        lectures=[
            (
                "Lecture 01: Time value of money",
                "Present worth P = F / (1 + i)^n converts a future amount F at "
                "interest rate i over n periods into today's dollars.",
            ),
        ],
    ),
    DemoCourse(
        "SYDE 286",
        "Mechanics of Deformable Solids",
        "1292394",
        due=[
            ("Quiz 2", -2, 12),
            ("Assignment 3: Shear and moment diagrams", 3, 23),
            ("Midterm test", 9, 19),
        ],
        lectures=[
            (
                "Lecture 01: Normal stress and strain",
                "Normal stress sigma = P / A. Normal strain epsilon = delta / L. "
                "In the elastic range Hooke's law gives sigma = E epsilon.",
            ),
            (
                "Lecture 07: Shear force and bending moment diagrams",
                "Cut the beam and use equilibrium to find the internal shear force "
                "V(x) and bending moment M(x). Sign convention: positive shear acts "
                "downward on the right face. Relations: dV/dx = -w(x) and dM/dx = V. "
                "A point load P makes the shear diagram jump by P. The moment is "
                "largest where the shear crosses zero.",
            ),
        ],
        announcements=[
            ("Lecture 07 notes posted", "Notes on shear and moment diagrams are on LEARN.")
        ],
    ),
    DemoCourse(
        "SYDE 292",
        "Circuits, Instrumentation, and Measurements",
        "1292783",
        lectures=[
            (
                "Lecture 01: Kirchhoff's laws",
                "Kirchhoff's current law: currents into a node sum to zero. "
                "Kirchhoff's voltage law: voltages around a loop sum to zero.",
            ),
        ],
    ),
    DemoCourse(
        "SYDE 292L",
        "Circuits Lab",
        "1296009",
        due=[("Lab 3 report", 2, 23)],
        lectures=[
            (
                "Lab 03 handout: Using a multimeter",
                "Measure voltage in parallel with the component and current in "
                "series with it. Start on the highest range.",
            ),
        ],
        announcements=[("Bring your multimeter", "Bring your multimeter to Lab 3.")],
    ),
]


def demo_pages(now: datetime | None = None, timezone: str = "America/Toronto") -> dict[str, Any]:
    """Return {url: page snapshot payload} plus content-module and download fixtures."""

    today = (now or datetime.now(ZoneInfo(timezone))).astimezone(ZoneInfo(timezone))
    pages: dict[str, dict[str, Any]] = {
        f"{LEARN}/d2l/home": {
            "url": f"{LEARN}/d2l/home",
            "title": "Homepage - Waterloo LEARN",
            "text": "My Courses",
            "links": [
                {
                    "text": f"{course.code} - Fall 2026",
                    "href": f"{LEARN}/d2l/lp/ouHome/home.d2l?ou={course.offering_id}",
                }
                for course in DEMO_COURSES
            ],
        }
    }
    content_modules: dict[str, list[dict[str, Any]]] = {}
    downloads: dict[str, dict[str, str]] = {}
    for course in DEMO_COURSES:
        ou = course.offering_id
        home = f"{LEARN}/d2l/lp/ouHome/home.d2l?ou={ou}"
        pages[home] = {"url": home, "title": f"{course.code} - {course.title}", "text": ""}

        calendar = f"{LEARN}/d2l/le/calendar/{ou}"
        events = []
        for index, (title, days, hour) in enumerate(course.due, start=1):
            event_url = f"{calendar}/event/{index}/detailsview"
            due = (today + timedelta(days=days)).replace(hour=hour, minute=59 if hour == 23 else 0)
            events.append({"text": f"{title} - Due", "href": event_url})
            pages[event_url] = {
                "url": event_url,
                "title": title,
                "text": f"{title} - Due\nDue {due.strftime('%b %d, %Y %I:%M %p')}",
            }
        pages[calendar] = {"url": calendar, "title": "Calendar", "text": "", "links": events}

        content = f"{LEARN}/d2l/le/content/{ou}/Home"
        items = []
        for index, (title, notes) in enumerate(course.lectures, start=1):
            item_url = f"{LEARN}/d2l/le/content/{ou}/viewContent/{index}/View"
            # LEARN quotes the item title and appends the file kind.
            items.append({"text": f"'{title}' - PDF document", "href": item_url})
            downloads[item_url] = {"filename": f"{title}.txt", "text": f"{title}\n\n{notes}\n"}
        pages[content] = {"url": content, "title": "Content", "text": "", "links": items}
        content_modules[content] = []

        news = f"{LEARN}/d2l/lms/news/main.d2l?ou={ou}"
        news_links = []
        for index, (title, body) in enumerate(course.announcements, start=1):
            detail = f"{LEARN}/d2l/le/news/{ou}/{index}/view"
            news_links.append({"text": title, "href": detail})
            pages[detail] = {"url": detail, "title": title, "text": body}
        pages[news] = {"url": news, "title": "Announcements", "text": "", "links": news_links}
    return {"pages": pages, "content_modules": content_modules, "downloads": downloads}
