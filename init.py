import os
import sys
import json
import re
import shutil
import secrets
import urllib.request
import urllib.error

def print_header(text):
    print(f"\n{'='*50}")
    print(f" 🚀 {text}")
    print(f"{'='*50}\n")

def main():
    print_header("Nova Voice Scheduling Agent — Initialization Script")
    
    # ── 1. Gather User Inputs ──────────────────────────────────────────────────
    vapi_api_key = input("Enter your Vapi Private API Key: ").strip()
    vapi_public_key = input("Enter your Vapi Public Key: ").strip()
    
    print("\nWhere is your backend deployed?")
    print("If you are running locally with ngrok, enter the ngrok HTTPS URL.")
    print("If you haven't deployed yet, you can leave this blank (defaults to http://localhost:8000)")
    backend_url = input("Backend URL: ").strip().rstrip("/")
    if not backend_url:
        backend_url = "http://localhost:8000"
    
    # ── 2. Handle Google Service Account ───────────────────────────────────────
    print_header("Google Calendar Credentials")
    print("Please provide the absolute path to the Google Service Account JSON file you downloaded.")
    print("Example: /Users/name/Downloads/credentials.json")
    
    while True:
        sa_path = input("Path to JSON file: ").strip()
        # Remove surrounding quotes if dragged-and-dropped in terminal
        if sa_path.startswith("'") and sa_path.endswith("'"):
            sa_path = sa_path[1:-1]
        elif sa_path.startswith('"') and sa_path.endswith('"'):
            sa_path = sa_path[1:-1]
            
        if not os.path.exists(sa_path):
            print("❌ File not found. Please try again.")
            continue
        try:
            with open(sa_path, 'r') as f:
                json.load(f) # Validate it's JSON
            # Copy to backend/service_account.json
            dest = os.path.join(os.path.dirname(__file__), "backend", "service_account.json")
            shutil.copy2(sa_path, dest)
            print(f"✅ Securely copied credentials to: {dest}")
            break
        except Exception as e:
            print(f"❌ Error reading JSON file: {e}")

    # ── 3. Calendar Configuration ──────────────────────────────────────────────
    print_header("Calendar Configuration")
    print("Which calendars should Nova check for conflicts?")
    print("Enter a comma-separated list of calendar emails (e.g., your.email@gmail.com, work@company.com).")
    print("The first calendar in the list will be where events are actually booked.")
    print("Press Enter to just use your default 'primary' calendar.")
    calendar_ids = input("Calendars: ").strip()
    if not calendar_ids:
        calendar_ids = "primary"

    # ── 4. Generate Webhook Secret ─────────────────────────────────────────────
    webhook_secret = secrets.token_urlsafe(32)
    print(f"\n🔐 Generated secure Vapi Webhook Secret: {webhook_secret}")
    
    # ── 5. Create Vapi Assistant ───────────────────────────────────────────────
    print_header("Registering Vapi Assistant")
    
    config_path = os.path.join(os.path.dirname(__file__), "backend", "vapi_assistant_config.json")
    try:
        with open(config_path, "r") as f:
            assistant_payload = json.load(f)
            
        # Update dynamic fields
        assistant_payload["serverUrl"] = f"{backend_url}/vapi/webhook"
        assistant_payload["serverUrlSecret"] = webhook_secret
        
        # Send API Request (using urllib to avoid requiring 'requests' before setup)
        req = urllib.request.Request(
            "https://api.vapi.ai/assistant",
            data=json.dumps(assistant_payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {vapi_api_key}",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (compatible; NovaSetup/1.0)"
            },
            method="POST"
        )
        
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode("utf-8"))
            assistant_id = data["id"]
            print(f"✅ Assistant created successfully! ID: {assistant_id}")
            
    except urllib.error.HTTPError as e:
        print(f"❌ Failed to create Vapi assistant. HTTP Error: {e.code}")
        print(e.read().decode("utf-8"))
        sys.exit(1)
    except Exception as e:
        print(f"❌ Failed to create Vapi assistant: {e}")
        sys.exit(1)

    # ── 6. Create .env File ────────────────────────────────────────────────────
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    with open(env_path, "w") as f:
        f.write(f"# ─── Google Calendar ───────────────────────────────────\n")
        f.write(f"GOOGLE_SERVICE_ACCOUNT_FILE=service_account.json\n")
        f.write(f"GOOGLE_CALENDAR_ID={calendar_ids}\n")
        f.write(f"DEFAULT_TIMEZONE=America/New_York\n\n")
        f.write(f"# ─── Vapi ──────────────────────────────────────────────\n")
        f.write(f"VAPI_API_KEY={vapi_api_key}\n")
        f.write(f"VAPI_PUBLIC_KEY={vapi_public_key}\n")
        f.write(f"VAPI_WEBHOOK_SECRET={webhook_secret}\n\n")
        f.write(f"# ─── Server ────────────────────────────────────────────\n")
        f.write(f"PORT=8000\n")
    print(f"✅ Generated .env file")

    # ── 7. Inject Frontend Config ──────────────────────────────────────────────
    index_path = os.path.join(os.path.dirname(__file__), "frontend", "index.html")
    try:
        with open(index_path, "r") as f:
            html = f.read()
        
        # Use regex to replace the key/ID values regardless of what's currently there
        # This works on first run (placeholder) AND on re-runs (old real values)
        html = re.sub(
            r'const VAPI_PUBLIC_KEY = "[^"]*"',
            f'const VAPI_PUBLIC_KEY = "{vapi_public_key}"',
            html
        )
        html = re.sub(
            r'const VAPI_ASSISTANT_ID = "[^"]*"',
            f'const VAPI_ASSISTANT_ID = "{assistant_id}"',
            html
        )
        
        with open(index_path, "w") as f:
            f.write(html)
        print(f"✅ Injected Vapi credentials into frontend/index.html")
    except Exception as e:
        print(f"⚠️ Could not update frontend/index.html automatically: {e}")

    # ── 8. Setup Complete ──────────────────────────────────────────────────────
    print_header("Setup Complete! 🎉")
    print("You are ready to run the agent. Here are your next steps:")
    print("1. cd backend")
    print("2. python -m venv venv")
    print("3. source venv/bin/activate  (or `venv\\Scripts\\activate` on Windows)")
    print("4. pip install -r requirements.txt")
    print("5. uvicorn main:app --reload --port 8000")
    print("\nThen, open frontend/index.html in your browser and start talking to Nova!")

if __name__ == "__main__":
    main()
