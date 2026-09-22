import html
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.models import Issue, JobRun, Source, SourceType
from app.opds import require_auth
from app.worker import execute_run
from pipeline.connector_factory import build_connector
from pipeline.settings_store import (
    get_cron_expression,
    get_interest_profile,
    get_relevance_threshold,
    set_cron_expression,
    set_interest_profile,
    set_relevance_threshold,
)

router = APIRouter(prefix="/ui", tags=["web"], dependencies=[Depends(require_auth)])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

SOURCE_TYPE_LABELS = [
    (SourceType.GUARDIAN_API.value, "Guardian API"),
    (SourceType.RSS.value, "RSS"),
    (SourceType.WEB_ARCHIVE.value, "Web archive"),
    (SourceType.X_BOOKMARKS.value, "X bookmarks"),
]


@router.get("/")
def index() -> RedirectResponse:
    return RedirectResponse(url="/ui/sources", status_code=303)


# --- Sources ---------------------------------------------------------------


@router.get("/sources", response_class=HTMLResponse)
def list_sources(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    sources = db.execute(select(Source).order_by(Source.created_at)).scalars().all()
    return templates.TemplateResponse(request, "sources/list.html", {"sources": sources})


@router.get("/sources/new", response_class=HTMLResponse)
def new_source_form(request: Request) -> HTMLResponse:
    context = {"source": None, "source_types": SOURCE_TYPE_LABELS, "error": None}
    return templates.TemplateResponse(request, "sources/form.html", context)


@router.post("/sources")
def create_source(
    name: str = Form(...),
    type: str = Form(...),  # noqa: A002 — matches the form field name
    section: str = Form(""),
    feed_url: str = Form(""),
    archive_url: str = Form(""),
    link_selector: str = Form(""),
    initial_fetch_limit: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    config = _config_from_form(
        type, section, feed_url, archive_url, link_selector, initial_fetch_limit
    )
    source = Source(name=name, type=SourceType(type), config=config)
    db.add(source)
    db.commit()
    return RedirectResponse(url="/ui/sources", status_code=303)


@router.get("/sources/{source_id}/edit", response_class=HTMLResponse)
def edit_source_form(
    source_id: str, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    context = {"source": source, "source_types": SOURCE_TYPE_LABELS, "error": None}
    return templates.TemplateResponse(request, "sources/form.html", context)


@router.post("/sources/{source_id}")
def update_source(
    source_id: str,
    name: str = Form(...),
    type: str = Form(...),  # noqa: A002
    section: str = Form(""),
    feed_url: str = Form(""),
    archive_url: str = Form(""),
    link_selector: str = Form(""),
    initial_fetch_limit: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    source.name = name
    source.config = _config_from_form(
        type, section, feed_url, archive_url, link_selector, initial_fetch_limit
    )
    db.commit()
    return RedirectResponse(url="/ui/sources", status_code=303)


@router.post("/sources/{source_id}/toggle", response_class=HTMLResponse)
def toggle_source(source_id: str, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    source.enabled = not source.enabled
    db.commit()
    return templates.TemplateResponse(request, "sources/_row.html", {"source": source})


@router.post("/sources/{source_id}/test-fetch", response_class=HTMLResponse)
def test_fetch_source(
    source_id: str, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> HTMLResponse:
    """Fetches from the source without persisting anything or moving its
    cursor — a preview, not a real ingest (PRD.md §7.1)."""
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")

    try:
        connector = build_connector(source, settings)
        result = connector.fetch_since(source.last_cursor)
    except Exception as exc:  # noqa: BLE001 — surfacing the failure to the UI is the point
        return HTMLResponse(f'<p class="error">Failed: {html.escape(str(exc))}</p>')

    if not result.items:
        return HTMLResponse('<p class="muted">No new items found.</p>')

    shown, remainder = result.items[:10], result.items[10:]
    items_html = "".join(f"<li>{html.escape(item.title)}</li>" for item in shown)
    more_html = f"<p class='muted'>...and {len(remainder)} more</p>" if remainder else ""
    body = f"<p>Found {len(result.items)} item(s):</p><ul>{items_html}</ul>{more_html}"
    return HTMLResponse(body)


def _config_from_form(
    type_: str,
    section: str,
    feed_url: str,
    archive_url: str,
    link_selector: str,
    initial_fetch_limit: str,
) -> dict:
    if type_ == SourceType.GUARDIAN_API.value:
        return {"section": section} if section else {}
    if type_ == SourceType.RSS.value:
        return {"feed_url": feed_url}
    if type_ == SourceType.WEB_ARCHIVE.value:
        config: dict = {"archive_url": archive_url, "link_selector": link_selector}
        if initial_fetch_limit:
            config["initial_fetch_limit"] = int(initial_fetch_limit)
        return config
    if type_ == SourceType.X_BOOKMARKS.value:
        return {}
    raise HTTPException(status_code=400, detail=f"Unknown source type: {type_}")


# --- Settings ----------------------------------------------------------------


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    context = {
        "interest_profile": get_interest_profile(db),
        "relevance_threshold": get_relevance_threshold(db),
        "cron_expression": get_cron_expression(db),
        "saved": False,
    }
    return templates.TemplateResponse(request, "settings.html", context)


@router.post("/settings", response_class=HTMLResponse)
def save_settings(
    request: Request,
    interest_profile: str = Form(""),
    relevance_threshold: float = Form(...),
    cron_expression: str = Form(...),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    set_interest_profile(db, interest_profile)
    set_relevance_threshold(db, relevance_threshold)
    set_cron_expression(db, cron_expression)
    context = {
        "interest_profile": interest_profile,
        "relevance_threshold": relevance_threshold,
        "cron_expression": cron_expression,
        "saved": True,
    }
    return templates.TemplateResponse(request, "settings.html", context)


# --- Runs & issues -----------------------------------------------------------


@router.get("/runs", response_class=HTMLResponse)
def list_runs(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    runs = db.execute(select(JobRun).order_by(JobRun.started_at.desc()).limit(50)).scalars().all()
    return templates.TemplateResponse(request, "runs/list.html", {"runs": runs})


@router.post("/runs/run-now")
def run_now() -> RedirectResponse:
    """Blocks until the run finishes (ARCHITECTURE.md §6) — fine at this
    project's scale; no background job queue needed for an occasional
    manual trigger."""
    execute_run()
    return RedirectResponse(url="/ui/runs", status_code=303)


@router.get("/issues", response_class=HTMLResponse)
def list_issues(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    issues = db.execute(select(Issue).order_by(Issue.issue_date.desc())).scalars().all()
    return templates.TemplateResponse(request, "issues/list.html", {"issues": issues})
