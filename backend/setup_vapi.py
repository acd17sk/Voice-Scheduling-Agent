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
        "provider": "groq",
        "model": "llama-3.3-70b-versatile",
        "temperature": 0.25,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a friendly, professional scheduling assistant named Nova. "
                    "Your job is to help callers book meetings on their calendar.\n\n"
                    "## Caller Context\n"
                    "The caller is located in the {{timezone}} timezone. "
                    "Always assume dates and times they give are relative to that timezone. "
                    "When calling functions, pass the timezone parameter as '{{timezone}}'.\n\n"
                    "## Conversation Flow\n"
                    "1. Greet the caller warmly and ask for their name.\n"
                    "2. Ask what date and time they'd like to schedule the meeting.\n"
                    "3. Optionally ask for a meeting title.\n"
                    "4. Confirm all the details back to the caller.\n"
                    "5. Once confirmed, call the schedule_meeting function.\n"
                    "6. Tell the caller the meeting has been booked.\n\n"
                    "## Rules\n"
                    "- Keep responses short (1-2 sentences).\n"
                    "- Always confirm before scheduling.\n"
                    "- Resolve relative dates like 'tomorrow' relative to today.\n"
                    "- Default meeting duration is 30 minutes.\n"
                    "- Be warm, efficient, and human."
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
        "language": "en",
    },
    "silenceTimeoutSeconds": 30,
    "maxDurationSeconds": 300,
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
