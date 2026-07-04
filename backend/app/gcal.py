"""Google Calendar integration (service account) — the Scheduler's real actuator.

Lets the agent read appointments and BOOK events (e.g., the lab the doctor ordered)
on a shared Google Calendar. Falls back to the seeded mock calendar when not
configured, so the demo runs fully offline and goes live with credentials.

Setup (live):
  1. Google Cloud: create a project, enable the Google Calendar API.
  2. Create a service account; download its JSON key.
  3. Share your demo Google Calendar with the service account's email
     ("Make changes to events").
  4. pip install google-api-python-client google-auth
     export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json
     export RELAY_CALENDAR_ID=<calendar id, e.g. ...@group.calendar.google.com>
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_DATA = REPO_ROOT / "demo-data"
SCOPES = ["https://www.googleapis.com/auth/calendar"]


def calendar_id() -> str | None:
    return os.environ.get("RELAY_CALENDAR_ID")


def is_configured() -> bool:
    return bool(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") and calendar_id())


def status() -> str:
    return "live (google)" if is_configured() else "mock"


def _service():
    from google.oauth2 import service_account  # lazy: only needed for live calls
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"], scopes=SCOPES
    )
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _mock_events() -> list[dict]:
    cal = json.loads((DEMO_DATA / "calendars.json").read_text())
    return [
        {"summary": e["title"], "start": e["start"], "link": ""}
        for e in cal["calendars"].get("robert", [])
    ]


def list_events(max_results: int = 10) -> list[dict]:
    if not is_configured():
        return _mock_events()
    svc = _service()
    now = datetime.now(timezone.utc).isoformat()
    res = (
        svc.events()
        .list(calendarId=calendar_id(), timeMin=now, maxResults=max_results,
              singleEvents=True, orderBy="startTime")
        .execute()
    )
    out = []
    for e in res.get("items", []):
        start = e.get("start", {})
        out.append({
            "summary": e.get("summary", ""),
            "start": start.get("dateTime", start.get("date", "")),
            "link": e.get("htmlLink", ""),
        })
    return out


def create_event(summary: str, start_iso: str, end_iso: str, description: str = "") -> dict:
    if not is_configured():
        return {"summary": summary, "start": start_iso, "link": "(mock — not sent to Google)", "mock": True}
    svc = _service()
    body = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_iso},
        "end": {"dateTime": end_iso},
    }
    e = svc.events().insert(calendarId=calendar_id(), body=body).execute()
    return {"summary": summary, "start": start_iso, "link": e.get("htmlLink", ""), "mock": False}
