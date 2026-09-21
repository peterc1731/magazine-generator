import secrets
from datetime import UTC, datetime
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, register_namespace, tostring

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.models import Issue

router = APIRouter(prefix="/opds", tags=["opds"])
_security = HTTPBasic(auto_error=False)

ATOM_NS = "http://www.w3.org/2005/Atom"
OPDS_NS = "http://opds-spec.org/2010/catalog"
CATALOG_TYPE = "application/atom+xml;profile=opds-catalog;kind=acquisition"

register_namespace("", ATOM_NS)


def require_auth(
    credentials: HTTPBasicCredentials | None = Depends(_security),
    settings: Settings = Depends(get_settings),
) -> None:
    """Basic auth in front of the catalog and downloads. If neither
    OPDS_BASIC_AUTH_USER nor OPDS_BASIC_AUTH_PASSWORD is configured, auth is
    treated as not set up yet and access is left open — matches how other
    optional settings (e.g. NTFY_TOPIC) behave in this codebase. HTTPS
    termination stays Caddy's job at deploy time (ARCHITECTURE.md §8); this
    is defense in depth so the app isn't wide open even without a proxy.
    """
    if not settings.opds_basic_auth_user and not settings.opds_basic_auth_password:
        return

    valid = (
        credentials is not None
        and secrets.compare_digest(credentials.username, settings.opds_basic_auth_user)
        and secrets.compare_digest(credentials.password, settings.opds_basic_auth_password)
    )
    if not valid:
        raise HTTPException(
            status_code=401, detail="Invalid credentials", headers={"WWW-Authenticate": "Basic"}
        )


@router.get("/", dependencies=[Depends(require_auth)])
def catalog(db: Session = Depends(get_db)) -> Response:
    issues = db.execute(select(Issue).order_by(Issue.issue_date.desc())).scalars().all()
    return Response(content=_build_catalog_feed(issues), media_type=CATALOG_TYPE)


@router.get("/issues/{issue_id}/download", dependencies=[Depends(require_auth)])
def download_issue(issue_id: str, db: Session = Depends(get_db)) -> FileResponse:
    issue = db.get(Issue, issue_id)
    if issue is None or not issue.file_ref:
        raise HTTPException(status_code=404, detail="Issue not found")
    return FileResponse(
        issue.file_ref, media_type="application/epub+zip", filename=Path(issue.file_ref).name
    )


@router.get("/issues/{issue_id}/cover", dependencies=[Depends(require_auth)])
def issue_cover(issue_id: str, db: Session = Depends(get_db)) -> FileResponse:
    issue = db.get(Issue, issue_id)
    if issue is None or not issue.cover_ref:
        raise HTTPException(status_code=404, detail="Cover not found")
    return FileResponse(issue.cover_ref, media_type="image/jpeg")


def _build_catalog_feed(issues: list[Issue]) -> bytes:
    feed = Element(f"{{{ATOM_NS}}}feed")
    feed.set("xmlns:opds", OPDS_NS)

    SubElement(feed, f"{{{ATOM_NS}}}id").text = "urn:magazine-generator:catalog"
    SubElement(feed, f"{{{ATOM_NS}}}title").text = "Magazine"
    updated = issues[0].created_at if issues else datetime.now(UTC)
    SubElement(feed, f"{{{ATOM_NS}}}updated").text = _rfc3339(updated)

    self_link = SubElement(feed, f"{{{ATOM_NS}}}link")
    self_link.set("rel", "self")
    self_link.set("href", "/opds/")
    self_link.set("type", CATALOG_TYPE)

    start_link = SubElement(feed, f"{{{ATOM_NS}}}link")
    start_link.set("rel", "start")
    start_link.set("href", "/opds/")
    start_link.set("type", "application/atom+xml;profile=opds-catalog;kind=navigation")

    for issue in issues:
        _add_entry(feed, issue)

    return b'<?xml version="1.0" encoding="utf-8"?>\n' + tostring(feed, encoding="utf-8")


def _add_entry(feed: Element, issue: Issue) -> None:
    entry = SubElement(feed, f"{{{ATOM_NS}}}entry")
    SubElement(entry, f"{{{ATOM_NS}}}id").text = f"urn:magazine-generator:issue:{issue.id}"
    issue_date = issue.issue_date.date().isoformat()
    SubElement(entry, f"{{{ATOM_NS}}}title").text = f"Magazine — {issue_date}"
    SubElement(entry, f"{{{ATOM_NS}}}updated").text = _rfc3339(issue.created_at)

    acquisition = SubElement(entry, f"{{{ATOM_NS}}}link")
    acquisition.set("rel", "http://opds-spec.org/acquisition")
    acquisition.set("href", f"/opds/issues/{issue.id}/download")
    acquisition.set("type", "application/epub+zip")

    if issue.cover_ref:
        for rel in ("http://opds-spec.org/image", "http://opds-spec.org/image/thumbnail"):
            cover_link = SubElement(entry, f"{{{ATOM_NS}}}link")
            cover_link.set("rel", rel)
            cover_link.set("href", f"/opds/issues/{issue.id}/cover")
            cover_link.set("type", "image/jpeg")

    SubElement(entry, f"{{{ATOM_NS}}}summary").text = f"{issue.article_count} article(s)"


def _rfc3339(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")
