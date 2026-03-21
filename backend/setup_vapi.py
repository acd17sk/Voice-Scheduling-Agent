"""
setup_vapi.py — Create the Vapi assistant via the Vapi API.

Usage:
    export VAPI_API_KEY="your-vapi-private-key"
    export BACKEND_WEBHOOK_URL="https://your-backend.onrender.com"
    python setup_vapi.py

This will print the assistant ID to plug into your frontend.
"""

import os
import json
import requests

VAPI_API_KEY = os.environ["VAPI_API_KEY"]
BACKEND_URL = os.environ.get("BACKEND_WEBHOOK_URL", "http://localhost:8000")

ASSISTANT_PAYLOAD = {
    "name": "Nova — Scheduling Assistant",
    "model": {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "temperature": 0.15,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a friendly, professional scheduling assistant named Nova. "
                    "Your job is to help callers book meetings on their calendar.\n\n"
                    "## Caller Context\n"
                    "Today's date is {{currentDate}}. "
                    "The caller is located in the {{timezone}} timezone. "
                    "Always assume dates and times they give are relative to that timezone. "
                    "When calling functions, pass the timezone parameter as '{{timezone}}'.\n\n"
                    "## Conversation Flow\n"
                    "1. Greet the caller warmly and ask for their name.\n"
                    "2. Ask what date and time they'd like to schedule the meeting.\n"
                    "3. Optionally ask for a meeting title.\n"
                    "4. Confirm all the details back to the caller.\n"
                    "5. Once confirmed, call the schedule_meeting function.\n"
                    "6. Tell the caller the meeting has been booked and ask if they need help with anything else.\n"
                    "7. Wait for the user to explicitly state they are finished before saying goodbye.\n\n"
                    "## Rules\n"
                    "- Keep responses short (1-2 sentences).\n"
                    "- Always confirm before scheduling.\n"
                    "- If you successfully book a meeting, you will receive an `event_id`.\n"
                    "- If the user changes their mind and wants to move a meeting OR change its title, DO NOT use `schedule_meeting` again to create a duplicate. Use the `reschedule_meeting` tool and pass the `event_id`. If they only want to change the title, pass the original date and time along with the new `title`.\n"
                    "- If the user wants to cancel a meeting you just booked, use `cancel_meeting` and pass the `event_id`.\n"
                    "- The user can book meetings for ANY valid calendar date in the future (e.g., 'March 25th', 'Next Friday', 'May 10th').\n"
                    "- IMPORTANT: The speech-to-text transcriber sometimes makes phonetic errors (e.g., transcribing '25th' as '20 fifth', or 'March' as 'Mark'). Intelligently interpret these phonetic mistakes as the intended date. NEVER correct the user or argue about how a date is spelled or formatted.\n"
                    "- Assume the user knows the correct date. Accept their requested date as valid and proceed with booking.\n"
                    "- Use today's date ({{currentDate}}) to calculate the exact calendar day for relative dates like 'tomorrow' or 'next week'.\n"
                    "- Always pass dates to functions in full ISO 8601 format (e.g. '2026-03-25T15:00:00').\n"
                    "- You can ONLY reschedule or cancel meetings that YOU booked during this current call. You do NOT have the ability to look up, modify, or delete pre-existing meetings on the user's calendar. If asked, politely explain this limitation.\n"
                    "- NEVER end the call immediately after booking a meeting. Always wait for the user to explicitly say they are done or ready to hang up.\n"
                    "- Default meeting duration is 30 minutes.\n"
                    "- Be warm, efficient, and human.\n\n"
                    "## Examples\n"
                    "Assume Today's date is Friday, March 20, 2026:\n\n"
                    "User: \"Let's meet on March 25th at 3 PM.\"\n"
                    "Nova: \"Perfect, I will schedule that for March 25th at 3 PM.\"\n"
                    "(Nova calls schedule_meeting with date_time=\"2026-03-25T15:00:00\")\n\n"
                    "User: \"How about tomorrow at 10 AM?\"\n"
                    "Nova: \"Sounds good, I'll book it for tomorrow, March 21st, at 10 AM.\"\n"
                    "(Nova calls schedule_meeting with date_time=\"2026-03-21T10:00:00\")\n\n"
                    "User: \"Let's do the 25th.\"\n"
                    "Nova: \"Just to confirm, do you mean March 25th?\""
                ),
            }
        ],
        "functions": [
            {
                "name": "schedule_meeting",
                "description": "Create a calendar event after user confirmation.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "The caller's name.",
                        },
                        "date_time": {
                            "type": "string",
                            "description": "ISO 8601 or natural language date/time.",
                        },
                        "title": {
                            "type": "string",
                            "description": "Optional meeting title.",
                        },
                        "duration_minutes": {
                            "type": "integer",
                            "description": "Meeting duration in minutes (default 30).",
                        },
                        "timezone": {
                            "type": "string",
                            "description": "The caller's IANA timezone (e.g. 'America/New_York'). Use the value from {{timezone}}.",
                        },
                    },
                    "required": ["name", "date_time"],
                },
            },
            {
                "name": "check_availability",
                "description": "Check if a particular time slot is available on the calendar.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date_time": {
                            "type": "string",
                            "description": "The date and time to check availability for.",
                        },
                        "duration_minutes": {
                            "type": "integer",
                            "description": "Duration in minutes to check (default 30).",
                        },
                        "timezone": {
                            "type": "string",
                            "description": "The caller's IANA timezone (e.g. 'America/New_York'). Use the value from {{timezone}}.",
                        },
                    },
                    "required": ["date_time"],
                },
            },
            {
                "name": "reschedule_meeting",
                "description": "Change the time of a meeting that you just booked. Requires the event_id from the original booking.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "event_id": {
                            "type": "string",
                            "description": "The unique event ID returned when the meeting was originally scheduled.",
                        },
                        "new_date_time": {
                            "type": "string",
                            "description": "The new requested date and time in ISO 8601 format.",
                        },
                        "title": {
                            "type": "string",
                            "description": "Optional new meeting title.",
                        },
                        "duration_minutes": {
                            "type": "integer",
                            "description": "Duration in minutes (default 30).",
                        },
                        "timezone": {
                            "type": "string",
                            "description": "The caller's IANA timezone.",
                        },
                    },
                    "required": ["event_id", "new_date_time"],
                },
            },
            {
                "name": "cancel_meeting",
                "description": "Delete or cancel a meeting that you just booked. Requires the event_id from the original booking.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "event_id": {
                            "type": "string",
                            "description": "The unique event ID of the meeting to cancel.",
                        },
                    },
                    "required": ["event_id"],
                },
            },
        ],
    },
    "voice": {
        "provider": "11labs",
        "voiceId": "21m00Tcm4TlvDq8ikWAM",
    },
    "firstMessage": "Hey there! I'm Nova, your scheduling assistant. I'd love to help you book a meeting. What's your name?",
    "serverUrl": f"{BACKEND_URL}/vapi/webhook",
    "transcriber": {
        "provider": "deepgram",
        "model": "nova-2",
        "language": "en-US",
        "smartFormat": True,
    },
    "silenceTimeoutSeconds": 30,
    "maxDurationSeconds": 300,
    "startSpeakingPlan": {
        "smartEndpointingEnabled": True,
        "waitSeconds": 1.5,
        "transcriptionEndpointingPlan": {
            "onNoPunctuationSeconds": 2.5,
            "onNumberSeconds": 2.0,
        }
    },
    "stopSpeakingPlan": {
        "numWords": 0,
        "voiceSeconds": 0.2,
        "backoffSeconds": 0.5,
    },
    "serverMessages": ["tool-calls", "status-update", "end-of-call-report", "transcript"],
}


def main():
    print("🚀 Creating Vapi assistant...")
    resp = requests.post(
        "https://api.vapi.ai/assistant",
        headers={
            "Authorization": f"Bearer {VAPI_API_KEY}",
            "Content-Type": "application/json",
        },
        json=ASSISTANT_PAYLOAD,
    )

    if resp.status_code in (200, 201):
        data = resp.json()
        assistant_id = data["id"]
        print(f"✅ Assistant created successfully!")
        print(f"   Assistant ID: {assistant_id}")
        print(f"   Name: {data.get('name')}")
        print()
        print(f"👉 Paste this into frontend/index.html:")
        print(f'   const VAPI_ASSISTANT_ID = "{assistant_id}";')
    else:
        print(f"❌ Error {resp.status_code}: {resp.text}")


if __name__ == "__main__":
    main()
