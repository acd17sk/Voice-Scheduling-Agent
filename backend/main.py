"""
Voice Scheduling Agent — FastAPI Webhook Server
Handles Vapi function calls and creates Google Calendar events.
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional
from pathlib import Path

from dotenv import load_dotenv

# Load .env file from the project root (one level up from backend/)
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

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


def reschedule_calendar_event(
    event_id: str,
    new_date_time: str,
    duration_minutes: int = 30,
    timezone: str = DEFAULT_TIMEZONE,
    title: Optional[str] = None,
) -> dict:
    """
    Reschedule an existing Google Calendar event.
    Updates the start and end times while leaving other details intact.
    """
    try:
        if not event_id:
            return {"success": False, "error": "No event_id provided."}

        # Parse the new date/time string
        try:
            dt = dateparser.parse(new_date_time)
        except (ParserError, ValueError):
            dt = None
        if dt is None:
            return {"success": False, "error": f"Could not parse new date/time: {new_date_time}"}

        # Localize timezone
        if dt.tzinfo is None:
            tz = pytz.timezone(timezone)
            dt = tz.localize(dt)

        end_dt = dt + timedelta(minutes=duration_minutes)

        service = get_calendar_service()
        primary_calendar_id = CALENDAR_IDS[0]

        # Use patch to update only specific fields
        event_body: dict = {
            "start": {"dateTime": dt.isoformat(), "timeZone": timezone},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": timezone},
        }
        
        if title:
            event_body["summary"] = title

        event = service.events().patch(calendarId=primary_calendar_id, eventId=event_id, body=event_body).execute()
        logger.info(f"✅ Event rescheduled: {event.get('htmlLink')}")

        return {
            "success": True,
            "event_id": event["id"],
            "event_link": event.get("htmlLink", ""),
            "start": event["start"]["dateTime"],
            "end": event["end"]["dateTime"],
            "message": "Meeting successfully rescheduled."
        }

    except Exception as e:
        logger.error(f"❌ Reschedule error: {e}")
        return {"success": False, "error": str(e)}


def cancel_calendar_event(event_id: str) -> dict:
    """
    Delete an existing Google Calendar event.
    """
    try:
        if not event_id:
            return {"success": False, "error": "No event_id provided."}

        service = get_calendar_service()
        primary_calendar_id = CALENDAR_IDS[0]

        service.events().delete(calendarId=primary_calendar_id, eventId=event_id).execute()
        logger.info(f"✅ Event cancelled: {event_id}")

        return {
            "success": True,
            "message": "Meeting successfully cancelled."
        }

    except Exception as e:
        logger.error(f"❌ Cancellation error: {e}")
        return {"success": False, "error": str(e)}


# ── Health Check ─────────────────────────────────────────────────────────────
@app.get("/")
async def root():
    return {"status": "ok", "service": "Voice Scheduling Agent", "version": "1.0.0"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


# ── Function Dispatcher ──────────────────────────────────────────────────────

def _handle_function(fn_name: str, fn_params: dict) -> dict:
    """Dispatch a function call by name and return the result dict."""
    if fn_name == "schedule_meeting":
        name = fn_params.get("name", "Guest")
        date_time = fn_params.get("date_time", "")
        title = fn_params.get("title", None)
        duration = fn_params.get("duration_minutes", 30)
        timezone = fn_params.get("timezone", DEFAULT_TIMEZONE)

        if not date_time:
            return {"success": False, "error": "No date/time provided."}
        return create_calendar_event(
            name=name,
            date_time=date_time,
            title=title,
            duration_minutes=duration,
            timezone=timezone,
        )

    elif fn_name == "check_availability":
        date_time = fn_params.get("date_time", "")
        duration = fn_params.get("duration_minutes", 30)
        timezone = fn_params.get("timezone", DEFAULT_TIMEZONE)

        if not date_time:
            return {"available": False, "error": "No date/time provided."}
        return check_calendar_availability(
            date_time=date_time,
            duration_minutes=duration,
            timezone=timezone,
        )

    elif fn_name == "reschedule_meeting":
        event_id = fn_params.get("event_id", "")
        new_date_time = fn_params.get("new_date_time", "")
        duration = fn_params.get("duration_minutes", 30)
        timezone = fn_params.get("timezone", DEFAULT_TIMEZONE)
        title = fn_params.get("title", None)

        if not new_date_time:
            return {"success": False, "error": "No new date/time provided."}
        return reschedule_calendar_event(
            event_id=event_id,
            new_date_time=new_date_time,
            duration_minutes=duration,
            timezone=timezone,
            title=title,
        )

    elif fn_name == "cancel_meeting":
        event_id = fn_params.get("event_id", "")
        return cancel_calendar_event(event_id=event_id)

    else:
        return {"error": f"Unknown function: {fn_name}"}


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

    # ── Handle function-call (legacy Vapi format) ─────────────────────────
    if message_type == "function-call":
        function_call = payload["message"].get("functionCall", {})
        fn_name = function_call.get("name", "")
        fn_params = function_call.get("parameters", {})

        logger.info(f"🔧 Function call: {fn_name} with params: {json.dumps(fn_params)}")
        result = _handle_function(fn_name, fn_params)
        return JSONResponse(content={"result": json.dumps(result)})

    # ── Handle tool-calls (current Vapi format) ──────────────────────────
    if message_type == "tool-calls":
        tool_call_list = payload["message"].get("toolCallList", [])
        results = []

        for tool_call in tool_call_list:
            tool_call_id = tool_call.get("id", "")
            function_info = tool_call.get("function", {})
            fn_name = function_info.get("name", "")

            # arguments can be a JSON string or a dict
            fn_args = function_info.get("arguments", {})
            if isinstance(fn_args, str):
                try:
                    fn_args = json.loads(fn_args)
                except json.JSONDecodeError:
                    fn_args = {}

            logger.info(f"🔧 Tool call [{tool_call_id}]: {fn_name} with params: {json.dumps(fn_args)}")
            result = _handle_function(fn_name, fn_args)
            results.append({
                "toolCallId": tool_call_id,
                "result": json.dumps(result),
            })

        return JSONResponse(content={"results": results})

    # ── Handle other event types (status-update, transcript, etc.) ───────
    if message_type == "status-update":
        status = payload["message"].get("status", "")
        logger.info(f"📊 Call status: {status}")

    elif message_type == "transcript":
        msg_data = payload.get("message", {})
        role = msg_data.get("role", "unknown")
        transcript = msg_data.get("transcript", "")
        if role == "user":
            logger.info(f"🗣️ YOU: {transcript}")
        elif role == "assistant":
            logger.info(f"🤖 NOVA: {transcript}")

    elif message_type == "end-of-call-report":
        logger.info("📞 Call ended.")
        summary = payload["message"].get("summary", "No summary.")
        logger.info(f"📝 Summary: {summary}")

    return JSONResponse(content={"status": "ok"})


# ── Run ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
