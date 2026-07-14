"""Relay backend — FastAPI.

Run from the repo root:
    uvicorn backend.app.main:app --reload

Then open http://127.0.0.1:8000/
"""

from __future__ import annotations

from pathlib import Path

import base64
import os
import secrets
import shutil
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import llm
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from . import audit, care_context, gcal, guardrails, orchestrator, permissions, planner
from .models import ActorRequest, ApproveRequest, AskRequest, ConsentRequest, RejectRequest
from .store import store

REPO_ROOT = Path(__file__).resolve().parents[2]
INDEX_HTML = REPO_ROOT / "web" / "index.html"


def _background_watch_loop(interval: int) -> None:
    time.sleep(min(10, interval))  # an early first scan so the demo fires soon after start
    while True:
        try:
            orchestrator.run_proactive_scan()
        except Exception:  # noqa: BLE001 - never let the background job crash the server
            pass
        time.sleep(interval)


def _start_background_watch() -> None:
    try:
        interval = int(os.environ.get("RELAY_WATCH_INTERVAL", "120"))
    except ValueError:
        interval = 120
    if interval <= 0:  # RELAY_WATCH_INTERVAL=0 disables the proactive job
        return
    threading.Thread(target=_background_watch_loop, args=(interval,), daemon=True).start()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _start_background_watch()  # runs under uvicorn; not during TestClient (no lifespan)
    yield


app = FastAPI(title="Intensive Vibe Coding Capstone Project: CarePilot — Caregiver Concierge", lifespan=lifespan)


@app.middleware("http")
async def _access_gate(request, call_next):
    """Single shared-password gate for deployed instances.

    OFF when RELAY_ACCESS_PASSWORD is unset (local dev / tests). When set, every
    request needs HTTP Basic auth with that password (any username). /health is
    exempt so uptime checks work. This protects the LLM key + health data on a
    public URL; it is NOT per-user auth (see SECURITY.md).
    """
    password = os.environ.get("RELAY_ACCESS_PASSWORD")
    if password and request.url.path != "/health":
        header = request.headers.get("authorization", "")
        authorized = False
        if header.startswith("Basic "):
            try:
                _, _, supplied = base64.b64decode(header[6:]).decode("utf-8").partition(":")
                authorized = secrets.compare_digest(supplied, password)
            except Exception:  # noqa: BLE001 - any decode error = unauthorized
                authorized = False
        if not authorized:
            return Response(
                "Authentication required.",
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="CarePilot"'},
            )
    return await call_next(request)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "llm": llm.is_configured(), "calendar": gcal.status()}


def _restricted(kind: str) -> dict:
    return {"restricted": True, "kind": kind}


def _plan_for(actor: str, plan: dict | None):
    """Calendar-view roles see the schedule, but the briefing one-pager contains
    medical detail (meds/allergies) — redact it for non-medical roles."""
    if not permissions.can(actor, "calendar_view"):
        return _restricted("schedule")
    if plan and not permissions.can(actor, "medical_documents"):
        return {**plan, "briefing": "🔒 Restricted — the handoff briefing contains medical detail"}
    return plan


def _filtered_state(actor: str) -> dict:
    """Return only what `actor` is authorized to see (design doc §4)."""
    full = store.state()
    med = permissions.can(actor, "medical_documents")
    return {
        "actor": actor,
        "role": permissions.role_of(actor),
        "is_admin": permissions.is_admin(actor),
        "roster": permissions.roster(),
        "consent": {**care_context.consent_block(), "revoked": store.consent_revoked},
        "notifications": store.notifications_for(actor),
        "reconciliation": full["reconciliation"] if med else _restricted("medical detail"),
        "plan": _plan_for(actor, full["plan"]),
        "watch": full["watch"] if med else _restricted("health observations"),
        "approvals": full["approvals"] if med else [],
        "outbox": full["outbox"] if med else [],
        "audit": audit.entries() if permissions.can(actor, "audit_log_view") else _restricted("audit log"),
    }


def _require_admin(actor: str) -> None:
    if not permissions.is_admin(actor):
        raise HTTPException(403, "This action is limited to the care coordinator.")


def _require_subject_or_admin(actor: str) -> None:
    if not (permissions.is_admin(actor) or permissions.role_of(actor) == "data_subject"):
        raise HTTPException(403, "Only the coordinator or the care recipient can do this.")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(INDEX_HTML)


@app.get("/api/state")
def get_state(actor: str = "maya") -> dict:
    return _filtered_state(actor)


@app.post("/api/reconcile")
def post_reconcile(actor: str = "maya") -> dict:
    _require_admin(actor)
    return orchestrator.run_reconcile(actor)


ALLOWED_UPLOAD_SUFFIXES = {".pdf", ".md", ".txt"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


@app.post("/api/reconcile/upload")
async def post_reconcile_upload(actor: str = "maya", files: list[UploadFile] = File(...)) -> dict:
    """Live ingestion of an uploaded after-visit document → Reconciler → queued draft."""
    _require_admin(actor)
    tmpdir = Path(tempfile.mkdtemp(prefix="relay-upload-"))
    try:
        paths: list[Path] = []
        for f in files:
            suffix = Path(f.filename or "").suffix.lower()
            if suffix not in ALLOWED_UPLOAD_SUFFIXES:
                raise HTTPException(400, f"Unsupported file type '{suffix}'. Use PDF, MD, or TXT.")
            content = await f.read()
            if len(content) > MAX_UPLOAD_BYTES:
                raise HTTPException(413, "File too large (max 10 MB).")
            dest = tmpdir / (Path(f.filename).name or "upload")
            dest.write_bytes(content)
            paths.append(dest)
        try:
            return orchestrator.run_reconcile_upload(paths, actor)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 - surface extraction/LLM errors to the UI
            raise HTTPException(400, f"Could not process the document: {exc}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@app.post("/api/scheduler/cover")
def post_scheduler(actor: str = "maya") -> dict:
    _require_admin(actor)
    return orchestrator.run_scheduler(actor)


@app.post("/api/watcher/scan")
def post_watcher(actor: str = "maya") -> dict:
    _require_admin(actor)
    return orchestrator.run_watcher(actor)


@app.get("/api/calendar")
def get_calendar(actor: str = "maya") -> dict:
    if not permissions.can(actor, "calendar_view"):
        raise HTTPException(403, "Calendar access is not permitted for your role.")
    return {
        "status": gcal.status(),
        "upcoming": gcal.list_events(),
        "created": store.calendar_events(),
    }


@app.post("/api/calendar/schedule-lab")
def post_schedule_lab(actor: str = "maya") -> dict:
    _require_admin(actor)
    return orchestrator.schedule_ordered_lab(actor)


@app.get("/api/briefer")
def get_briefing(actor: str = "maya", appt: int = 0) -> dict:
    _require_admin(actor)  # briefings contain medical detail (meds/allergies)
    return orchestrator.generate_briefing(appt, actor)


@app.post("/api/agent")
def post_agent(req: AskRequest) -> dict:
    """The agent entry point: free-text request → guardrails → planner → tools.

    Guardrails screen BEFORE planning: an emergency or a dose-change request is
    answered by the safety lane and never reaches the planner. Consent-revoked
    pauses the agent entirely. Everything the planner does either reads state or
    queues a draft for human approval.
    """
    _require_admin(req.actor)
    screened = guardrails.route(req.text)
    if screened["kind"] != "info":
        audit.log(req.actor, f"agent_request ({screened['kind']})", detail=req.text)
        return {"handled_by": "guardrails", **screened}
    if store.consent_revoked:
        audit.log("agent", "blocked_by_consent", detail="agent request while consent revoked")
        return {"handled_by": "consent", "blocked": True,
                "reason": "Agent autonomy is paused — the care recipient's consent is revoked."}
    audit.log(req.actor, "agent_request", detail=req.text)
    return {"handled_by": "planner", **planner.run(req.text, req.actor)}


@app.post("/api/access/{resource}")
def post_access(resource: str, req: ActorRequest) -> dict:
    """The unauthorized-access path: allow → return data; deny → 403 + log + notify."""
    cap = permissions.RESOURCE_CAP.get(resource)
    if cap and permissions.can(req.actor, cap):
        audit.log(req.actor, "access_granted", resource=resource)
        return {"granted": True, "resource": resource, "content": care_context.sensitive_resource(resource)}
    audit.log(req.actor, "access_DENIED", detail=f"attempted to open {resource}", resource=resource)
    store.notify("maya", f"{care_context.name_of(req.actor)} attempted to open '{resource}' and was blocked.")
    raise HTTPException(403, f"Access to '{resource}' is not permitted for your role.")


@app.get("/api/data/export")
def export_data(actor: str = "maya") -> dict:
    """Data-subject access request: everything the system holds about the recipient."""
    _require_subject_or_admin(actor)
    audit.log(actor, "data_exported", detail=f"data export for {care_context.RECIPIENT_NAME}")
    full = store.state()
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_subject": care_context.RECIPIENT_NAME,
        "requested_by": actor,
        "record": care_context.subject_record(),
        "reconciliation": full["reconciliation"],
        "plan": full["plan"],
        "watch": full["watch"],
        "approvals": full["approvals"],
        "outbox": full["outbox"],
        "audit_log": audit.entries(),
    }


@app.post("/api/data/erase")
def erase_data(req: ActorRequest) -> dict:
    """Right to erasure: clear the agent's working record (the audit trail is kept)."""
    _require_subject_or_admin(req.actor)
    counts = store.erase_subject_record()
    audit.log(req.actor, "data_erased", detail="erased the care recipient's working record")
    return {"erased": True, **counts}


@app.post("/api/consent")
def post_consent(req: ConsentRequest) -> dict:
    _require_subject_or_admin(req.actor)
    store.set_consent_revoked(req.revoked)
    audit.log(
        req.actor,
        "consent_revoked" if req.revoked else "consent_restored",
        detail="agent autonomy " + ("paused" if req.revoked else "resumed"),
    )
    return {"revoked": req.revoked}


@app.post("/api/approvals/{aid}/approve")
def post_approve(aid: str, req: ApproveRequest) -> dict:
    _require_admin(req.actor)
    appr = orchestrator.approve(aid, req.actor, req.edited_text)
    if not appr:
        raise HTTPException(404, "approval not found or already resolved")
    return appr


@app.post("/api/approvals/{aid}/reject")
def post_reject(aid: str, req: RejectRequest) -> dict:
    _require_admin(req.actor)
    appr = orchestrator.reject(aid, req.actor, req.reason)
    if not appr:
        raise HTTPException(404, "approval not found or already resolved")
    return appr


@app.post("/api/ask")
def post_ask(req: AskRequest) -> dict:
    return orchestrator.handle_ask(req.text, req.actor)


@app.post("/api/reset")
def post_reset() -> dict:
    orchestrator.reset()
    return {"ok": True}
