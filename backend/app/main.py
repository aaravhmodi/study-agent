# ruff: noqa: E501

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.config import get_settings
from app.db.database import SessionLocal, ensure_schema
from app.models import Assessment, ChangeEvent, Course, Resource, SyncRun
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.rag import RagService
from app.services.study_context import relevant_coursework, study_guidance

app = FastAPI(title="StudyAgent", version="0.1.0")
_DASHBOARD_PAGE = Path(__file__).parent / "web" / "dashboard.html"


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    """Answer a student question using the indexed course materials."""
    try:
        return RagService(get_settings()).ask(
            request.question, request.course_code, fresh=request.fresh
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "browser_mode": get_settings().browser_mode}


@app.get("/courses")
def courses() -> list[dict[str, Any]]:
    ensure_schema()
    with SessionLocal() as session:
        rows = session.scalars(
            select(Course).where(Course.active.is_(True)).order_by(Course.name)
        ).all()
        return [
            {
                "id": course.id,
                "code": course.code,
                "name": course.name,
                "term": course.term,
                "url": course.url,
                "last_scanned_at": _iso(course.last_scanned_at),
                "assessment_count": len(course.assessments),
                "resource_count": len(course.resources),
            }
            for course in rows
        ]


@app.get("/courses/{course_id}")
def course_detail(course_id: str) -> dict[str, Any]:
    ensure_schema()
    with SessionLocal() as session:
        course = session.get(Course, course_id)
        if course is None or not course.active:
            raise HTTPException(status_code=404, detail="Course not found")
        return _course_detail_payload(course)


@app.get("/assessments")
def assessments() -> list[dict[str, Any]]:
    ensure_schema()
    with SessionLocal() as session:
        rows = session.execute(
            select(Assessment, Course)
            .join(Course, Assessment.course_id == Course.id)
            .where(Course.active.is_(True))
            .order_by(Assessment.due_at.is_(None), Assessment.due_at)
        ).all()
        return [
            {
                "id": assessment.id,
                "course_id": course.id,
                "course": course.code or course.name,
                "title": assessment.title,
                "type": assessment.assessment_type,
                "due_at": _iso(assessment.due_at),
                "description": assessment.description,
                "status": _assessment_status(assessment.due_at, assessment.status),
                "source_url": assessment.source_url,
            }
            for assessment, course in rows
        ]


@app.get("/assessments/{assessment_id}")
def assessment_detail(assessment_id: str) -> dict[str, Any]:
    ensure_schema()
    with SessionLocal() as session:
        assessment = session.get(Assessment, assessment_id)
        if assessment is None or not assessment.course.active:
            raise HTTPException(status_code=404, detail="Assessment not found")
        return _assessment_detail_payload(assessment)


@app.post("/assessments/{assessment_id}/complete")
def complete_assessment(assessment_id: str) -> dict[str, Any]:
    return _set_assessment_status(assessment_id, "COMPLETED")


@app.post("/assessments/{assessment_id}/reopen")
def reopen_assessment(assessment_id: str) -> dict[str, Any]:
    ensure_schema()
    with SessionLocal() as session:
        assessment = session.get(Assessment, assessment_id)
        if assessment is None or not assessment.course.active:
            raise HTTPException(status_code=404, detail="Assessment not found")
        assessment.status = _assessment_status(assessment.due_at, "UPCOMING")
        session.commit()
        return _assessment_detail_payload(assessment)


@app.get("/resources")
def resources() -> list[dict[str, Any]]:
    ensure_schema()
    with SessionLocal() as session:
        rows = session.execute(
            select(Resource, Course)
            .join(Course, Resource.course_id == Course.id)
            .where(Course.active.is_(True))
            .order_by(Resource.first_seen_at.desc())
        ).all()
        return [
            {
                "id": resource.id,
                "course": course.code or course.name,
                "title": resource.title,
                "type": resource.resource_type,
                "description": resource.description,
                "url": resource.url,
                "first_seen_at": _iso(resource.first_seen_at),
            }
            for resource, course in rows
        ]


@app.get("/changes")
def changes() -> list[dict[str, Any]]:
    with SessionLocal() as session:
        rows = session.scalars(
            select(ChangeEvent).order_by(ChangeEvent.detected_at.desc()).limit(50)
        ).all()
        return [
            {
                "id": change.id,
                "type": change.type,
                "description": change.description,
                "detected_at": _iso(change.detected_at),
            }
            for change in rows
        ]


def _course_detail_payload(course: Course) -> dict[str, Any]:
    assessments_data = [
        _assessment_summary(assessment, course)
        for assessment in sorted(
            course.assessments,
            key=lambda item: (item.due_at is None, item.due_at or datetime.max.replace(tzinfo=UTC)),
        )
    ]
    return {
        "id": course.id,
        "code": course.code,
        "name": course.name,
        "term": course.term,
        "url": course.url,
        "last_scanned_at": _iso(course.last_scanned_at),
        "assessments": assessments_data,
        "completed_assessments": sum(item["status"] == "COMPLETED" for item in assessments_data),
        "resources": [
            {
                "id": resource.id,
                "title": resource.title,
                "type": resource.resource_type,
                "url": resource.url,
                "description": resource.description,
                "first_seen_at": _iso(resource.first_seen_at),
            }
            for resource in sorted(course.resources, key=lambda item: item.title.casefold())
        ],
        "announcements": [
            {
                "id": announcement.id,
                "title": announcement.title,
                "body": announcement.body,
                "published_at": _iso(announcement.published_at),
                "source_url": announcement.source_url,
            }
            for announcement in sorted(
                course.announcements,
                key=lambda item: item.published_at or datetime.min.replace(tzinfo=UTC),
                reverse=True,
            )
        ],
    }


def _assessment_summary(assessment: Assessment, course: Course) -> dict[str, Any]:
    return {
        "id": assessment.id,
        "course_id": course.id,
        "course": course.code or course.name,
        "title": assessment.title,
        "type": assessment.assessment_type,
        "due_at": _iso(assessment.due_at),
        "weight_percent": assessment.weight_percent,
        "description": assessment.description,
        "status": _assessment_status(assessment.due_at, assessment.status),
        "source_url": assessment.source_url,
    }


def _assessment_detail_payload(assessment: Assessment) -> dict[str, Any]:
    course = assessment.course
    return {
        **_assessment_summary(assessment, course),
        "coursework": relevant_coursework(assessment, course.resources),
        "study_guidance": study_guidance(assessment),
    }


def _set_assessment_status(assessment_id: str, status: str) -> dict[str, Any]:
    ensure_schema()
    with SessionLocal() as session:
        assessment = session.get(Assessment, assessment_id)
        if assessment is None or not assessment.course.active:
            raise HTTPException(status_code=404, detail="Assessment not found")
        assessment.status = status
        session.commit()
        return _assessment_detail_payload(assessment)


@app.get("/api/dashboard")
def dashboard_data() -> dict[str, Any]:
    ensure_schema()
    with SessionLocal() as session:
        last_sync = session.scalar(select(SyncRun).order_by(SyncRun.started_at.desc()))
        active_courses = session.scalars(
            select(Course).where(Course.active.is_(True)).order_by(Course.name)
        ).all()
        assessment_rows = session.execute(
            select(Assessment, Course)
            .join(Course, Assessment.course_id == Course.id)
            .where(Course.active.is_(True))
            .order_by(Assessment.due_at.is_(None), Assessment.due_at)
            .limit(30)
        ).all()
        recent_changes = session.scalars(
            select(ChangeEvent).order_by(ChangeEvent.detected_at.desc()).limit(10)
        ).all()
        return {
            "last_sync": {
                "started_at": _iso(last_sync.started_at),
                "finished_at": _iso(last_sync.finished_at),
                "status": last_sync.status,
                "courses_found": last_sync.courses_found,
                "assessments_found": last_sync.assessments_found,
                "resources_found": last_sync.resources_found,
            }
            if last_sync
            else None,
            "courses": [
                {
                    "id": course.id,
                    "code": course.code,
                    "name": course.name,
                    "assessment_count": len(course.assessments),
                    "resource_count": len(course.resources),
                    "completed_assessment_count": sum(
                        assessment.status == "COMPLETED" for assessment in course.assessments
                    ),
                }
                for course in active_courses
            ],
            "assessments": [
                {
                    "id": assessment.id,
                    "course_id": course.id,
                    "course": course.code or course.name,
                    "title": assessment.title,
                    "type": assessment.assessment_type,
                    "due_at": _iso(assessment.due_at),
                    "description": assessment.description,
                    "status": _assessment_status(assessment.due_at, assessment.status),
                }
                for assessment, course in assessment_rows
            ],
            "changes": [
                {
                    "type": change.type,
                    "description": change.description,
                    "detected_at": _iso(change.detected_at),
                }
                for change in recent_changes
            ],
        }


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard() -> str:
    return _DASHBOARD_PAGE.read_text(encoding="utf-8")


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone().isoformat(timespec="minutes")


def _assessment_status(due_at: datetime | None, stored_status: str) -> str:
    if due_at is None:
        return stored_status
    compare_at = due_at if due_at.tzinfo else due_at.replace(tzinfo=UTC)
    return "OVERDUE" if compare_at < datetime.now(UTC) else stored_status


DASHBOARD_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>StudyAgent Dashboard</title>
<style>
body{font-family:system-ui,sans-serif;background:#f5f7fb;color:#172033;margin:0}main{max-width:1180px;margin:auto;padding:32px 20px}
h1{margin:0 0 6px}.muted{color:#667085}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin:22px 0}
.card{background:#fff;border:1px solid #e4e7ec;border-radius:14px;padding:18px;box-shadow:0 2px 8px #1018280d}.card h2{font-size:16px;margin:0 0 14px}
.metric{font-size:28px;font-weight:700}.course{display:flex;justify-content:space-between;gap:16px;border-top:1px solid #eaecf0;padding:10px 0}.course:first-child{border-top:0}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:10px 8px;border-top:1px solid #eaecf0}th{color:#667085;font-weight:600}.pill{border-radius:99px;padding:3px 8px;font-size:12px;background:#eef4ff;color:#175cd3}.overdue{background:#fef3f2;color:#b42318}.empty{color:#667085;padding:8px 0}
a{color:#175cd3;text-decoration:none}
</style></head><body><main>
<h1>StudyAgent</h1><div class="muted">Local academic workload dashboard · <a href="/docs">API docs</a></div>
<div id="summary" class="grid"></div>
<div class="grid"><section class="card"><h2>Active courses</h2><div id="courses"></div></section>
<section class="card"><h2>Recent changes</h2><div id="changes"></div></section></div>
<section class="card"><h2>Assessments</h2><div id="assessments"></div></section>
</main><script>
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const date = value => value ? new Date(value).toLocaleString() : 'No date';
async function load(){
 const data=await fetch('/api/dashboard').then(r=>r.json()); const sync=data.last_sync;
 document.querySelector('#summary').innerHTML = [['Courses',data.courses.length],['Assessments',sync?.assessments_found ?? 0],['Resources',sync?.resources_found ?? 0],['Last sync',sync?.finished_at ? date(sync.finished_at) : 'Never']].map(([label,value])=>`<section class="card"><div class="muted">${esc(label)}</div><div class="metric">${esc(value)}</div></section>`).join('');
 document.querySelector('#courses').innerHTML=data.courses.length?data.courses.map(c=>`<div class="course"><span><b>${esc(c.code||c.name)}</b><br><span class="muted">${esc(c.name)}</span></span><span class="muted">${c.resource_count} resources<br>${c.assessment_count} assessments</span></div>`).join(''):'<div class="empty">Run sync to discover courses.</div>';
 document.querySelector('#changes').innerHTML=data.changes.length?data.changes.map(c=>`<div class="course"><span><b>${esc(c.type)}</b><br>${esc(c.description)}</span><span class="muted">${esc(date(c.detected_at))}</span></div>`).join(''):'<div class="empty">No stored change events yet.</div>';
 document.querySelector('#assessments').innerHTML=data.assessments.length?`<table><thead><tr><th>Course</th><th>Assessment</th><th>Type</th><th>Due</th><th>Status</th></tr></thead><tbody>${data.assessments.map(a=>`<tr><td>${esc(a.course)}</td><td>${esc(a.title)}</td><td>${esc(a.type)}</td><td>${esc(date(a.due_at))}</td><td><span class="pill ${a.status==='OVERDUE'?'overdue':''}">${esc(a.status)}</span></td></tr>`).join('')}</tbody></table>`:'<div class="empty">No assessments stored yet.</div>';
}
load().catch(error=>{document.querySelector('main').insertAdjacentHTML('beforeend',`<p class="overdue card">Dashboard could not load: ${esc(error)}</p>`)});
</script></body></html>"""
