# ruff: noqa: E501

from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.config import get_settings
from app.db.database import SessionLocal, ensure_schema
from app.models import Assessment, ChangeEvent, Course, Resource, SyncRun
from app.services.study_context import relevant_coursework, study_guidance

app = FastAPI(title="StudyAgent", version="0.1.0")


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
    return INTERACTIVE_DASHBOARD_HTML


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


INTERACTIVE_DASHBOARD_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>StudyAgent Dashboard</title>
<style>
body{font-family:system-ui,sans-serif;background:#f5f7fb;color:#172033;margin:0}main{max-width:1220px;margin:auto;padding:32px 20px}
h1{margin:0 0 6px}.muted{color:#667085}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin:22px 0}
.card{background:#fff;border:1px solid #e4e7ec;border-radius:14px;padding:18px;box-shadow:0 2px 8px #1018280d}.card h2{font-size:16px;margin:0 0 14px}
.metric{font-size:28px;font-weight:700}.course{display:flex;justify-content:space-between;gap:16px;border-top:1px solid #eaecf0;padding:12px 0}.course:first-child{border-top:0}
button{font:inherit}.clickable{cursor:pointer;text-align:left;background:transparent;border:0;width:100%;color:inherit}.clickable:hover{background:#f8faff}.toolbar{display:flex;justify-content:space-between;align-items:center;gap:12px}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:10px 8px;border-top:1px solid #eaecf0}th{color:#667085;font-weight:600}.pill{border-radius:99px;padding:3px 8px;font-size:12px;background:#eef4ff;color:#175cd3;white-space:nowrap}.overdue{background:#fef3f2;color:#b42318}.completed{background:#ecfdf3;color:#027a48}.empty{color:#667085;padding:8px 0}.detail{margin:22px 0}.hidden{display:none}.link{color:#175cd3}.resource{border-top:1px solid #eaecf0;padding:10px 0}.resource:first-child{border-top:0}.action{border:0;border-radius:8px;padding:8px 12px;background:#175cd3;color:#fff;cursor:pointer}.secondary{background:#eef4ff;color:#175cd3}
ul{padding-left:20px}li{margin:8px 0}.small{font-size:13px}
</style></head><body><main>
<h1>StudyAgent</h1><div class="muted">Click a course or assessment to see your work, completion state, relevant coursework, and study method. <a href="/docs">API docs</a></div>
<div id="summary" class="grid"></div>
<section id="detail" class="card detail hidden"><div id="detail-content"></div></section>
<div class="grid"><section class="card"><div class="toolbar"><h2>Courses</h2><span class="muted small">click to open</span></div><div id="courses"></div></section>
<section class="card"><h2>Recent changes</h2><div id="changes"></div></section></div>
<section class="card"><h2>Assessments — click one for study guidance</h2><div id="assessments"></div></section>
</main><script>
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const date = value => value ? new Date(value).toLocaleString() : 'No date';
const statusPill = status => `<span class="pill ${status==='OVERDUE'?'overdue':''} ${status==='COMPLETED'?'completed':''}">${esc(status)}</span>`;
const resourceLink = resource => resource.url ? `<a class="link" target="_blank" rel="noreferrer" href="${esc(resource.url)}">${esc(resource.title)}</a>` : esc(resource.title);
async function getJson(path, options){const response=await fetch(path,options);if(!response.ok)throw new Error(await response.text());return response.json()}
function showDetail(html){const detail=document.querySelector('#detail');document.querySelector('#detail-content').innerHTML=html;detail.classList.remove('hidden');detail.scrollIntoView({behavior:'smooth',block:'start'})}
function closeDetail(){document.querySelector('#detail').classList.add('hidden')}
async function openCourse(id){
 const c=await getJson(`/courses/${encodeURIComponent(id)}`);
 showDetail(`<div class="toolbar"><div><h2>${esc(c.code||c.name)}</h2><div class="muted">${esc(c.name)} · ${esc(c.term||'')}</div></div><button class="action secondary" data-close>Close</button></div>
 <p><b>${c.completed_assessments}</b> of <b>${c.assessments.length}</b> assessments marked completed · <b>${c.resources.length}</b> collected resources</p>
 <h3>Assessments</h3><div>${c.assessments.length?c.assessments.map(a=>`<button class="clickable course" data-assessment="${esc(a.id)}"><span><b>${esc(a.title)}</b><br><span class="muted">${esc(a.type)} · ${esc(date(a.due_at))}</span></span>${statusPill(a.status)}</button>`).join(''):'<div class="empty">No assessments found.</div>'}</div>
 <h3>Coursework you have</h3><div>${c.resources.length?c.resources.map(r=>`<div class="resource"><b>${resourceLink(r)}</b> <span class="muted">${esc(r.type)}</span>${r.description?`<div class="muted small">${esc(r.description)}</div>`:''}</div>`).join(''):'<div class="empty">No resources found.</div>'}</div>
 <h3>Announcements</h3><div>${c.announcements.length?c.announcements.slice(0,10).map(a=>`<div class="resource"><b>${esc(a.title)}</b><div class="muted small">${esc(a.body||'')}</div></div>`).join(''):'<div class="empty">No announcements stored.</div>'}</div>`);
}
async function openAssessment(id){
 const a=await getJson(`/assessments/${encodeURIComponent(id)}`);
 const action=a.status==='COMPLETED'?`<button class="action secondary" data-reopen="${esc(a.id)}">Mark not completed</button>`:`<button class="action" data-complete="${esc(a.id)}">Mark completed</button>`;
 showDetail(`<div class="toolbar"><div><h2>${esc(a.title)}</h2><div class="muted">${esc(a.course)} · ${esc(a.type)} · due ${esc(date(a.due_at))}</div></div><div>${action} <button class="action secondary" data-close>Close</button></div></div>
 <p>${statusPill(a.status)} ${a.weight_percent==null?'':' · '+esc(a.weight_percent)+'%'}</p>${a.description?`<p>${esc(a.description)}</p>`:''}
 <h3>Relevant coursework</h3><div>${a.coursework.length?a.coursework.map(r=>`<div class="resource"><b>${resourceLink(r)}</b> <span class="muted">${esc(r.type)}</span><div class="muted small">${esc(r.match_reason)}</div>${r.description?`<div class="muted small">${esc(r.description)}</div>`:''}</div>`).join(''):'<div class="empty">No matching course resources yet. Run sync after the instructor posts material.</div>'}</div>
 <h3>How to study for it</h3><ul>${a.study_guidance.map(step=>`<li>${esc(step)}</li>`).join('')}</ul>`);
}
async function load(){
 const data=await getJson('/api/dashboard'); const sync=data.last_sync;
 document.querySelector('#summary').innerHTML=[['Courses',data.courses.length],['Assessments',sync?.assessments_found??0],['Resources',sync?.resources_found??0],['Last sync',sync?.finished_at?date(sync.finished_at):'Never']].map(([label,value])=>`<section class="card"><div class="muted">${esc(label)}</div><div class="metric">${esc(value)}</div></section>`).join('');
 document.querySelector('#courses').innerHTML=data.courses.length?data.courses.map(c=>`<button class="clickable course" data-course="${esc(c.id)}"><span><b>${esc(c.code||c.name)}</b><br><span class="muted">${esc(c.name)}</span></span><span class="muted">${c.completed_assessment_count}/${c.assessment_count} complete<br>${c.resource_count} resources</span></button>`).join(''):'<div class="empty">Run sync to discover courses.</div>';
 document.querySelector('#changes').innerHTML=data.changes.length?data.changes.map(c=>`<div class="course"><span><b>${esc(c.type)}</b><br>${esc(c.description)}</span><span class="muted">${esc(date(c.detected_at))}</span></div>`).join(''):'<div class="empty">No stored change events yet.</div>';
 document.querySelector('#assessments').innerHTML=data.assessments.length?`<table><thead><tr><th>Course</th><th>Assessment</th><th>Type</th><th>Due</th><th>Status</th></tr></thead><tbody>${data.assessments.map(a=>`<tr><td>${esc(a.course)}</td><td><button class="clickable" data-assessment="${esc(a.id)}"><b>${esc(a.title)}</b></button></td><td>${esc(a.type)}</td><td>${esc(date(a.due_at))}</td><td>${statusPill(a.status)}</td></tr>`).join('')}</tbody></table>`:'<div class="empty">No assessments stored yet.</div>';
}
document.querySelector('#courses').addEventListener('click',event=>{const target=event.target.closest('[data-course]');if(target)openCourse(target.dataset.course).catch(showError)});
document.querySelector('#assessments').addEventListener('click',event=>{const target=event.target.closest('[data-assessment]');if(target)openAssessment(target.dataset.assessment).catch(showError)});
document.querySelector('#detail').addEventListener('click',event=>{
 const target=event.target.closest('button');
 if(!target)return;
 if(target.hasAttribute('data-close')){event.preventDefault();closeDetail();return}
 if(target.dataset.assessment){event.preventDefault();openAssessment(target.dataset.assessment).catch(showError);return}
 if(target.dataset.complete){event.preventDefault();event.stopPropagation();changeStatus(target.dataset.complete,'complete',target);return}
 if(target.dataset.reopen){event.preventDefault();event.stopPropagation();changeStatus(target.dataset.reopen,'reopen',target);return}
});
async function changeStatus(id,action,button){
 if(button){button.disabled=true;button.textContent='Saving...'}
 try{
  await getJson(`/assessments/${encodeURIComponent(id)}/${action}`,{method:'POST'});
  await load();
  await openAssessment(id);
 }catch(error){
  if(button){button.disabled=false;button.textContent=action==='complete'?'Mark completed':'Mark not completed'}
  showError(error);
 }
}
function showError(error){showDetail(`<p class="overdue">Could not save this change: ${esc(error?.message||error)}</p>`)}
load().catch(showError);
</script></body></html>"""
