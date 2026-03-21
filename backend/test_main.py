"""
Unit tests for the Voice Scheduling Agent backend.
Tests cover date parsing, event payload construction, availability checking,
webhook dispatch logic, and error handling.

Run with: pytest test_main.py -v
"""

import json
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import pytest
import pytz
from fastapi.testclient import TestClient

from main import (
    app, 
    create_calendar_event, 
    check_calendar_availability,
    reschedule_calendar_event,
    cancel_calendar_event
)


client = TestClient(app)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_webhook_payload(fn_name: str, parameters: dict) -> dict:
    """Build a Vapi function-call webhook payload."""
    return {
        "message": {
            "type": "function-call",
            "functionCall": {
                "name": fn_name,
                "parameters": parameters,
            },
        }
    }


def _mock_calendar_insert(event_body: dict) -> dict:
    """Simulate a successful Google Calendar insert response."""
    return {
        "id": "test_event_123",
        "htmlLink": "https://calendar.google.com/event?id=test_event_123",
        "summary": event_body["summary"],
        "start": {"dateTime": event_body["start"]["dateTime"]},
        "end": {"dateTime": event_body["end"]["dateTime"]},
    }


def _build_mock_service(insert_side_effect=None, freebusy_response=None):
    """
    Build a mock Google Calendar service object.
    Supports mocking both events().insert() and freebusy().query().
    """
    mock_service = MagicMock()

    # Mock events().insert().execute()
    mock_insert = MagicMock()
    if insert_side_effect:
        mock_insert.execute.side_effect = insert_side_effect
    else:
        # Default: capture the body arg and return a realistic response
        def insert_handler(calendarId, body):
            mock_req = MagicMock()
            mock_req.execute.return_value = _mock_calendar_insert(body)
            return mock_req
        mock_service.events.return_value.insert = insert_handler

    # Mock freebusy().query().execute()
    if freebusy_response is not None:
        mock_freebusy_req = MagicMock()
        mock_freebusy_req.execute.return_value = freebusy_response
        mock_service.freebusy.return_value.query.return_value = mock_freebusy_req

    # Mock events().patch().execute()
    mock_service.events.return_value.patch.return_value.execute.return_value = {
        "id": "test_event_123",
        "htmlLink": "https://calendar.google.com/event?id=test_event_123",
        "start": {"dateTime": "2025-06-16T14:00:00-04:00"},
        "end": {"dateTime": "2025-06-16T14:30:00-04:00"},
    }

    # Mock events().delete().execute()
    mock_service.events.return_value.delete.return_value.execute.return_value = ""

    return mock_service


# ── Tests: Health Endpoints ──────────────────────────────────────────────────

class TestHealthEndpoints:
    def test_root(self):
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "Voice Scheduling Agent"

    def test_health(self):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"


# ── Tests: Date Parsing & Event Creation ─────────────────────────────────────

class TestCreateCalendarEvent:
    """Test create_calendar_event with mocked Google Calendar API."""

    @patch("main.get_calendar_service")
    @patch("main.check_calendar_availability")
    def test_iso8601_date(self, mock_check, mock_get_service):
        mock_get_service.return_value = _build_mock_service()
        mock_check.return_value = {"available": True}

        result = create_calendar_event(
            name="Alice",
            date_time="2025-06-15T14:00:00",
        )

        assert result["success"] is True
        assert result["event_id"] == "test_event_123"
        assert result["summary"] == "Meeting with Alice"
        assert "2025-06-15" in result["start"]
        assert "14:00" in result["start"]

    @patch("main.get_calendar_service")
    @patch("main.check_calendar_availability")
    def test_natural_language_date(self, mock_check, mock_get_service):
        mock_get_service.return_value = _build_mock_service()
        mock_check.return_value = {"available": True}

        result = create_calendar_event(
            name="Bob",
            date_time="January 20 2025 at 3pm",
        )

        assert result["success"] is True
        assert result["summary"] == "Meeting with Bob"
        assert "2025-01-20" in result["start"]
        assert "15:00" in result["start"]

    @patch("main.get_calendar_service")
    @patch("main.check_calendar_availability")
    def test_custom_title(self, mock_check, mock_get_service):
        mock_get_service.return_value = _build_mock_service()
        mock_check.return_value = {"available": True}

        result = create_calendar_event(
            name="Charlie",
            date_time="2025-03-10T10:00:00",
            title="Project Kickoff",
        )

        assert result["success"] is True
        assert result["summary"] == "Project Kickoff"

    @patch("main.get_calendar_service")
    @patch("main.check_calendar_availability")
    def test_default_title_uses_name(self, mock_check, mock_get_service):
        mock_get_service.return_value = _build_mock_service()
        mock_check.return_value = {"available": True}

        result = create_calendar_event(
            name="Dana",
            date_time="2025-03-10T10:00:00",
        )

        assert result["summary"] == "Meeting with Dana"

    @patch("main.get_calendar_service")
    @patch("main.check_calendar_availability")
    def test_custom_duration(self, mock_check, mock_get_service):
        mock_get_service.return_value = _build_mock_service()
        mock_check.return_value = {"available": True}

        result = create_calendar_event(
            name="Eve",
            date_time="2025-07-01T09:00:00",
            duration_minutes=60,
        )

        assert result["success"] is True
        # end should be 1 hour after start
        assert "10:00" in result["end"]

    @patch("main.get_calendar_service")
    @patch("main.check_calendar_availability")
    def test_timezone_naive_gets_localized(self, mock_check, mock_get_service):
        """A timezone-naive datetime should be localized to DEFAULT_TIMEZONE."""
        mock_get_service.return_value = _build_mock_service()
        mock_check.return_value = {"available": True}

        result = create_calendar_event(
            name="Frank",
            date_time="2025-08-01T12:00:00",
            timezone="America/New_York",
        )

        assert result["success"] is True
        # The isoformat output should contain offset info (e.g. -04:00 or -05:00)
        assert "-04:00" in result["start"] or "-05:00" in result["start"]

    @patch("main.get_calendar_service")
    @patch("main.check_calendar_availability")
    def test_timezone_aware_preserved(self, mock_check, mock_get_service):
        """A timezone-aware datetime should keep its original timezone."""
        mock_get_service.return_value = _build_mock_service()
        mock_check.return_value = {"available": True}

        result = create_calendar_event(
            name="Grace",
            date_time="2025-08-01T12:00:00+02:00",
        )

        assert result["success"] is True
        assert "+02:00" in result["start"]

    @patch("main.check_calendar_availability")
    def test_unparseable_date_returns_error(self, mock_check):
        """An invalid date string should return an error without calling the API."""
        mock_check.return_value = {"available": True}

        result = create_calendar_event(
            name="Hank",
            date_time="not-a-real-date-at-all xyz",
        )

        assert result["success"] is False
        assert "Could not parse" in result["error"]

    @patch("main.get_calendar_service")
    @patch("main.check_calendar_availability")
    def test_calendar_api_error(self, mock_check, mock_get_service):
        """If the Calendar API raises, we should get a graceful error response."""
        mock_service = MagicMock()
        mock_req = MagicMock()
        mock_req.execute.side_effect = Exception("API quota exceeded")
        mock_service.events.return_value.insert.return_value = mock_req
        mock_get_service.return_value = mock_service
        mock_check.return_value = {"available": True}

        result = create_calendar_event(
            name="Ivan",
            date_time="2025-06-15T14:00:00",
        )

        assert result["success"] is False
        assert "API quota exceeded" in result["error"]

    @patch("main.get_calendar_service")
    @patch("main.check_calendar_availability")
    def test_event_payload_structure(self, mock_check, mock_get_service):
        """Verify the event body sent to the Calendar API has the right shape."""
        captured_body = {}
        mock_service = MagicMock()
        mock_check.return_value = {"available": True}

        def capture_insert(calendarId, body):
            captured_body.update(body)
            mock_req = MagicMock()
            mock_req.execute.return_value = _mock_calendar_insert(body)
            return mock_req

        mock_service.events.return_value.insert = capture_insert
        mock_get_service.return_value = mock_service

        create_calendar_event(
            name="Julia",
            date_time="2025-09-01T16:00:00",
            title="Design Review",
            duration_minutes=45,
        )

        assert captured_body["summary"] == "Design Review"
        assert captured_body["description"] == "Scheduled via Voice Assistant for Julia."
        assert "dateTime" in captured_body["start"]
        assert "timeZone" in captured_body["start"]
        assert "dateTime" in captured_body["end"]
        assert captured_body["attendees"] == []
        assert captured_body["reminders"] == {"useDefault": True}


# ── Tests: Check Availability ────────────────────────────────────────────────

class TestCheckCalendarAvailability:
    """Test check_calendar_availability with mocked freebusy API."""

    @patch("main.get_calendar_service")
    @patch("main.CALENDAR_IDS", ["primary"])
    def test_slot_available(self, mock_get_service):
        freebusy_response = {
            "calendars": {
                "primary": {"busy": []},
            }
        }
        mock_get_service.return_value = _build_mock_service(
            freebusy_response=freebusy_response
        )

        result = check_calendar_availability(date_time="2025-06-15T14:00:00")

        assert result["available"] is True
        assert result["conflicts"] == []
        assert "available" in result["message"].lower()

    @patch("main.get_calendar_service")
    @patch("main.CALENDAR_IDS", ["primary"])
    def test_slot_busy_single_conflict(self, mock_get_service):
        freebusy_response = {
            "calendars": {
                "primary": {
                    "busy": [
                        {
                            "start": "2025-06-15T14:00:00-04:00",
                            "end": "2025-06-15T14:30:00-04:00",
                        }
                    ]
                },
            }
        }
        mock_get_service.return_value = _build_mock_service(
            freebusy_response=freebusy_response
        )

        result = check_calendar_availability(date_time="2025-06-15T14:00:00")

        assert result["available"] is False
        assert len(result["conflicts"]) == 1
        assert "is 1 conflicting" in result["message"]

    @patch("main.get_calendar_service")
    @patch("main.CALENDAR_IDS", ["primary"])
    def test_slot_busy_multiple_conflicts(self, mock_get_service):
        freebusy_response = {
            "calendars": {
                "primary": {
                    "busy": [
                        {
                            "start": "2025-06-15T14:00:00-04:00",
                            "end": "2025-06-15T14:15:00-04:00",
                        },
                        {
                            "start": "2025-06-15T14:20:00-04:00",
                            "end": "2025-06-15T14:30:00-04:00",
                        },
                    ]
                },
            }
        }
        mock_get_service.return_value = _build_mock_service(
            freebusy_response=freebusy_response
        )

        result = check_calendar_availability(date_time="2025-06-15T14:00:00")

        assert result["available"] is False
        assert len(result["conflicts"]) == 2
        assert "are 2 conflicting" in result["message"]

    def test_unparseable_date_returns_error(self):
        result = check_calendar_availability(date_time="garbage input")

        assert result["available"] is False
        assert "Could not parse" in result["error"]

    @patch("main.get_calendar_service")
    @patch("main.CALENDAR_IDS", ["primary"])
    def test_api_error_returns_graceful_error(self, mock_get_service):
        mock_service = MagicMock()
        mock_req = MagicMock()
        mock_req.execute.side_effect = Exception("Freebusy API error")
        mock_service.freebusy.return_value.query.return_value = mock_req
        mock_get_service.return_value = mock_service

        result = check_calendar_availability(date_time="2025-06-15T14:00:00")

        assert result["available"] is False
        assert "Freebusy API error" in result["error"]


# ── Tests: Meeting Management ────────────────────────────────────────────────

class TestMeetingManagement:
    """Test reschedule_calendar_event and cancel_calendar_event."""

    @patch("main.get_calendar_service")
    def test_reschedule_success(self, mock_get_service):
        mock_get_service.return_value = _build_mock_service()

        result = reschedule_calendar_event(
            event_id="test_event_123",
            new_date_time="2025-06-16T14:00:00",
        )

        assert result["success"] is True
        assert result["event_id"] == "test_event_123"
        assert result["message"] == "Meeting successfully rescheduled."
        
        # Verify patch was called with correct structure
        mock_service = mock_get_service.return_value
        patch_call_kwargs = mock_service.events.return_value.patch.call_args.kwargs
        assert patch_call_kwargs["eventId"] == "test_event_123"
        assert "start" in patch_call_kwargs["body"]
        assert "2025-06-16T14:00:00" in patch_call_kwargs["body"]["start"]["dateTime"]

    @patch("main.get_calendar_service")
    def test_reschedule_with_title(self, mock_get_service):
        mock_get_service.return_value = _build_mock_service()

        result = reschedule_calendar_event(
            event_id="test_event_123",
            new_date_time="2025-06-16T14:00:00",
            title="Updated Meeting Name",
        )

        assert result["success"] is True
        
        mock_service = mock_get_service.return_value
        patch_call_kwargs = mock_service.events.return_value.patch.call_args.kwargs
        assert patch_call_kwargs["body"]["summary"] == "Updated Meeting Name"

    def test_reschedule_missing_id(self):
        result = reschedule_calendar_event(event_id="", new_date_time="2025-06-16T14:00:00")
        assert result["success"] is False
        assert "No event_id" in result["error"]

    @patch("main.get_calendar_service")
    def test_cancel_success(self, mock_get_service):
        mock_get_service.return_value = _build_mock_service()

        result = cancel_calendar_event(event_id="test_event_123")

        assert result["success"] is True
        assert result["message"] == "Meeting successfully cancelled."
        
        # Verify delete was called with correct event_id
        mock_service = mock_get_service.return_value
        delete_call_kwargs = mock_service.events.return_value.delete.call_args.kwargs
        assert delete_call_kwargs["eventId"] == "test_event_123"

    def test_cancel_missing_id(self):
        result = cancel_calendar_event(event_id="")
        assert result["success"] is False
        assert "No event_id" in result["error"]

# ── Tests: Webhook Dispatch ──────────────────────────────────────────────────

@patch("main.VAPI_WEBHOOK_SECRET", "")
class TestWebhookDispatch:
    """Test the /vapi/webhook endpoint with various message types."""

    @patch("main.create_calendar_event")
    def test_schedule_meeting_success(self, mock_create):
        mock_create.return_value = {
            "success": True,
            "event_id": "evt_001",
            "event_link": "https://calendar.google.com/event?id=evt_001",
            "summary": "Meeting with Alice",
            "start": "2025-06-15T14:00:00-04:00",
            "end": "2025-06-15T14:30:00-04:00",
        }

        payload = _make_webhook_payload("schedule_meeting", {
            "name": "Alice",
            "date_time": "2025-06-15T14:00:00",
        })

        resp = client.post("/vapi/webhook", json=payload)
        assert resp.status_code == 200

        result = json.loads(resp.json()["result"])
        assert result["success"] is True
        assert result["event_id"] == "evt_001"

        mock_create.assert_called_once_with(
            name="Alice",
            date_time="2025-06-15T14:00:00",
            title=None,
            duration_minutes=30,
            timezone="America/New_York",
        )

    def test_schedule_meeting_missing_date(self):
        payload = _make_webhook_payload("schedule_meeting", {
            "name": "Alice",
            "date_time": "",
        })

        resp = client.post("/vapi/webhook", json=payload)
        assert resp.status_code == 200

        result = json.loads(resp.json()["result"])
        assert result["success"] is False
        assert "No date/time" in result["error"]

    @patch("main.check_calendar_availability")
    def test_check_availability_success(self, mock_check):
        mock_check.return_value = {
            "available": True,
            "message": "The time slot is available.",
            "conflicts": [],
        }

        payload = _make_webhook_payload("check_availability", {
            "date_time": "2025-06-15T14:00:00",
        })

        resp = client.post("/vapi/webhook", json=payload)
        assert resp.status_code == 200

        result = json.loads(resp.json()["result"])
        assert result["available"] is True

        mock_check.assert_called_once_with(
            date_time="2025-06-15T14:00:00",
            duration_minutes=30,
            timezone="America/New_York",
        )

    def test_check_availability_missing_date(self):
        payload = _make_webhook_payload("check_availability", {
            "date_time": "",
        })

        resp = client.post("/vapi/webhook", json=payload)
        assert resp.status_code == 200

        result = json.loads(resp.json()["result"])
        assert result["available"] is False
        assert "No date/time" in result["error"]

    def test_unknown_function(self):
        payload = _make_webhook_payload("do_something_else", {"foo": "bar"})

        resp = client.post("/vapi/webhook", json=payload)
        assert resp.status_code == 200

        result = json.loads(resp.json()["result"])
        assert "Unknown function" in result["error"]
        assert "do_something_else" in result["error"]

    def test_status_update_returns_ok(self):
        payload = {
            "message": {
                "type": "status-update",
                "status": "in-progress",
            }
        }

        resp = client.post("/vapi/webhook", json=payload)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_end_of_call_report_returns_ok(self):
        payload = {
            "message": {
                "type": "end-of-call-report",
                "summary": "User booked a meeting for next Tuesday.",
            }
        }

        resp = client.post("/vapi/webhook", json=payload)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_invalid_json_returns_400(self):
        resp = client.post(
            "/vapi/webhook",
            content=b"this is not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400
        assert "Invalid JSON" in resp.json()["error"]

    def test_unknown_message_type_returns_ok(self):
        payload = {
            "message": {
                "type": "some-unknown-type",
            }
        }

        resp = client.post("/vapi/webhook", json=payload)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @patch("main.create_calendar_event")
    def test_schedule_meeting_with_all_params(self, mock_create):
        mock_create.return_value = {
            "success": True,
            "event_id": "evt_002",
            "event_link": "https://calendar.google.com/event?id=evt_002",
            "summary": "Sprint Planning",
            "start": "2025-06-15T09:00:00-04:00",
            "end": "2025-06-15T10:00:00-04:00",
        }

        payload = _make_webhook_payload("schedule_meeting", {
            "name": "Bob",
            "date_time": "2025-06-15T09:00:00",
            "title": "Sprint Planning",
            "duration_minutes": 60,
        })

        resp = client.post("/vapi/webhook", json=payload)
        assert resp.status_code == 200

        result = json.loads(resp.json()["result"])
        assert result["success"] is True
        assert result["summary"] == "Sprint Planning"

        mock_create.assert_called_once_with(
            name="Bob",
            date_time="2025-06-15T09:00:00",
            title="Sprint Planning",
            duration_minutes=60,
            timezone="America/New_York",
        )

# ── Tests: Webhook Security ─────────────────────────────────────────────────

class TestWebhookSecurity:
    """Test webhook secret verification."""

    @patch("main.VAPI_WEBHOOK_SECRET", "test-secret-123")
    def test_missing_secret_returns_401(self):
        """Request without x-vapi-secret header should be rejected."""
        payload = _make_webhook_payload("schedule_meeting", {
            "name": "Alice",
            "date_time": "2025-06-15T14:00:00",
        })

        resp = client.post("/vapi/webhook", json=payload)
        assert resp.status_code == 401
        assert resp.json()["error"] == "Unauthorized"

    @patch("main.VAPI_WEBHOOK_SECRET", "test-secret-123")
    def test_wrong_secret_returns_401(self):
        """Request with wrong x-vapi-secret header should be rejected."""
        payload = _make_webhook_payload("schedule_meeting", {
            "name": "Alice",
            "date_time": "2025-06-15T14:00:00",
        })

        resp = client.post(
            "/vapi/webhook",
            json=payload,
            headers={"x-vapi-secret": "wrong-secret"},
        )
        assert resp.status_code == 401
        assert resp.json()["error"] == "Unauthorized"

    @patch("main.VAPI_WEBHOOK_SECRET", "test-secret-123")
    @patch("main.create_calendar_event")
    def test_correct_secret_passes(self, mock_create):
        """Request with correct x-vapi-secret should be processed normally."""
        mock_create.return_value = {
            "success": True,
            "event_id": "evt_secure",
            "event_link": "https://calendar.google.com/event?id=evt_secure",
            "summary": "Meeting with Alice",
            "start": "2025-06-15T14:00:00-04:00",
            "end": "2025-06-15T14:30:00-04:00",
        }

        payload = _make_webhook_payload("schedule_meeting", {
            "name": "Alice",
            "date_time": "2025-06-15T14:00:00",
        })

        resp = client.post(
            "/vapi/webhook",
            json=payload,
            headers={"x-vapi-secret": "test-secret-123"},
        )
        assert resp.status_code == 200
        result = json.loads(resp.json()["result"])
        assert result["success"] is True

    @patch("main.VAPI_WEBHOOK_SECRET", "")
    def test_no_secret_configured_allows_all(self):
        """When VAPI_WEBHOOK_SECRET is empty, all requests should pass through."""
        payload = {
            "message": {
                "type": "status-update",
                "status": "in-progress",
            }
        }

        resp = client.post("/vapi/webhook", json=payload)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
