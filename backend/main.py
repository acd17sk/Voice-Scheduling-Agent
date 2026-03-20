"""
Voice Scheduling Agent — FastAPI Webhook Server
Handles Vapi function calls and creates Google Calendar events.
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from google.oauth2 import service_account
from googleapiclient.discovery import build
from dateutil import parser as dateparser
from dateutil.parser import ParserError
import pytz

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("voice-scheduler")

# ── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(title="Voice Scheduling Agent", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Google Calendar Setup ────────────────────────────────────────────────────
SCOPES = ["https://www.googleapis.com/auth/calendar"]
# CALENDAR_IDS can be a comma-separated list of calendars to check. Events will be booked on the first one.
CALENDAR_IDS = [cid.strip() for cid in os.getenv("GOOGLE_CALENDAR_ID", "primary").split(",")]
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")
SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
DEFAULT_TIMEZONE = os.getenv("DEFAULT_TIMEZONE", "America/New_York")
VAPI_WEBHOOK_SECRET = os.getenv("VAPI_WEBHOOK_SECRET", "")


def get_calendar_service():
    """Build and return an authenticated Google Calendar service."""
    if SERVICE_ACCOUNT_JSON:
        info = json.loads(SERVICE_ACCOUNT_JSON)
        credentials = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        credentials = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES
        )
    return build("calendar", "v3", credentials=credentials)


def create_calendar_event(
    name: str,
    date_time: str,
    title: Optional[str] = None,
    duration_minutes: int = 30,
    timezone: str = DEFAULT_TIMEZONE,
) -> dict:
    """
    Create a Google Calendar event.
    Returns the event details or an error dict.
    """
    try:
        # Phase 3: Prevent double booking by re-checking availability right before insertion
        availability = check_calendar_availability(date_time, duration_minutes, timezone)
        if not availability.get("available"):
            return {
                "success": False,
                "error": "The requested time slot has just been booked or is no longer available. Please ask the caller for a new time."
            }

        # Parse the date/time string first (validate before calling API)
        try:
            dt = dateparser.parse(date_time)
        except (ParserError, ValueError):
            dt = None
        if dt is None:
            return {"success": False, "error": f"Could not parse date/time: {date_time}"}

        # If no timezone info, localize to default
        if dt.tzinfo is None:
            tz = pytz.timezone(timezone)
            dt = tz.localize(dt)

        end_dt = dt + timedelta(minutes=duration_minutes)

        service = get_calendar_service()

        event_title = title if title else f"Meeting with {name}"
        event_body = {
            "summary": event_title,
            "description": f"Scheduled via Voice Assistant for {name}.",
            "start": {
                "dateTime": dt.isoformat(),
                "timeZone": timezone,
            },
            "end": {
                "dateTime": end_dt.isoformat(),
                "timeZone": timezone,
            },
            "attendees": [],
            "reminders": {
                "useDefault": True,
            },
        }

        # Book on the primary (first) calendar in the list
        primary_calendar_id = CALENDAR_IDS[0]
        event = service.events().insert(calendarId=primary_calendar_id, body=event_body).execute()
        logger.info(f"✅ Event created: {event.get('htmlLink')}")

        return {
            "success": True,
            "event_id": event["id"],
            "event_link": event.get("htmlLink", ""),
            "summary": event["summary"],
            "start": event["start"]["dateTime"],
            "end": event["end"]["dateTime"],
        }

    except Exception as e:
        logger.error(f"❌ Calendar error: {e}")
        return {"success": False, "error": str(e)}


def check_calendar_availability(
    date_time: str,
    duration_minutes: int = 30,
    timezone: str = DEFAULT_TIMEZONE,
) -> dict:
    """
    Check if a specific time slot is available on the calendar.
    Uses the Google Calendar freebusy API to find conflicts.
    Returns availability status and any conflicting busy windows.
    """
    try:
        # Parse the date/time string first (validate before calling API)
        try:
            dt = dateparser.parse(date_time)
        except (ParserError, ValueError):
            dt = None
        if dt is None:
            return {"available": False, "error": f"Could not parse date/time: {date_time}"}

        # If no timezone info, localize to default
        if dt.tzinfo is None:
            tz = pytz.timezone(timezone)
            dt = tz.localize(dt)

        end_dt = dt + timedelta(minutes=duration_minutes)

        service = get_calendar_service()

        # Query the freebusy API across all calendars
        freebusy_query = {
            "timeMin": dt.isoformat(),
            "timeMax": end_dt.isoformat(),
            "timeZone": timezone,
            "items": [{"id": cid} for cid in CALENDAR_IDS],
        }

        result = service.freebusy().query(body=freebusy_query).execute()
        
        # Aggregate busy slots from all checked calendars
        busy_slots = []
        for cid in CALENDAR_IDS:
            busy_slots.extend(result.get("calendars", {}).get(cid, {}).get("busy", []))

        if not busy_slots:
            logger.info(f"✅ Time slot available: {dt.isoformat()} - {end_dt.isoformat()}")
            return {
                "available": True,
                "message": f"The time slot from {dt.strftime('%I:%M %p')} to {end_dt.strftime('%I:%M %p')} on {dt.strftime('%B %d, %Y')} is available.",
                "conflicts": [],
            }
        else:
            conflicts = [
                {"start": slot["start"], "end": slot["end"]}
                for slot in busy_slots
            ]
            logger.info(f"❌ Time slot busy: {len(conflicts)} conflict(s)")
            return {
                "available": False,
                "message": f"That time slot is not available. There {'is' if len(conflicts) == 1 else 'are'} {len(conflicts)} conflicting event(s).",
                "conflicts": conflicts,
            }

    except Exception as e:
        logger.error(f"❌ Availability check error: {e}")
        return {"available": False, "error": str(e)}


# ── Health Check ─────────────────────────────────────────────────────────────
@app.get("/")
async def root():
    return {"status": "ok", "service": "Voice Scheduling Agent", "version": "1.0.0"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


# ── Vapi Webhook Endpoint ────────────────────────────────────────────────────
@app.post("/vapi/webhook")
async def vapi_webhook(request: Request):
    """
    Handle incoming Vapi webhook events.
    Vapi sends function-call requests here when the LLM invokes a tool.
    """
    # ── Webhook secret verification ──────────────────────────────────────
    if VAPI_WEBHOOK_SECRET:
        secret_header = request.headers.get("x-vapi-secret", "")
        if secret_header != VAPI_WEBHOOK_SECRET:
            logger.warning("Unauthorized webhook attempt: invalid x-vapi-secret")
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})

    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON"})

    message_type = payload.get("message", {}).get("type", "")
    logger.info(f"📩 Vapi webhook received: type={message_type}")

    # ── Handle function-call ─────────────────────────────────────────────
    if message_type == "function-call":
        function_call = payload["message"].get("functionCall", {})
        fn_name = function_call.get("name", "")
        fn_params = function_call.get("parameters", {})

        logger.info(f"🔧 Function call: {fn_name} with params: {json.dumps(fn_params)}")

        if fn_name == "schedule_meeting":
            name = fn_params.get("name", "Guest")
            date_time = fn_params.get("date_time", "")
            title = fn_params.get("title", None)
            duration = fn_params.get("duration_minutes", 30)
            timezone = fn_params.get("timezone", DEFAULT_TIMEZONE)

            if not date_time:
                result = {"success": False, "error": "No date/time provided."}
            else:
                result = create_calendar_event(
                    name=name,
                    date_time=date_time,
                    title=title,
                    duration_minutes=duration,
                    timezone=timezone,
                )

            return JSONResponse(content={"result": json.dumps(result)})

        elif fn_name == "check_availability":
            date_time = fn_params.get("date_time", "")
            duration = fn_params.get("duration_minutes", 30)
            timezone = fn_params.get("timezone", DEFAULT_TIMEZONE)

            if not date_time:
                result = {"available": False, "error": "No date/time provided."}
            else:
                result = check_calendar_availability(
                    date_time=date_time,
                    duration_minutes=duration,
                    timezone=timezone,
                )

            return JSONResponse(content={"result": json.dumps(result)})

        else:
            return JSONResponse(
                content={"result": json.dumps({"error": f"Unknown function: {fn_name}"})}
            )

    # ── Handle other event types (status-update, transcript, etc.) ───────
    if message_type == "status-update":
        status = payload["message"].get("status", "")
        logger.info(f"📊 Call status: {status}")

    if message_type == "end-of-call-report":
        logger.info("📞 Call ended.")
        summary = payload["message"].get("summary", "No summary.")
        logger.info(f"📝 Summary: {summary}")

    return JSONResponse(content={"status": "ok"})


# ── Run ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
