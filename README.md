# 🗓️ Nova — Voice Scheduling Agent

A real-time voice assistant that books meetings on Google Calendar through natural conversation.

**Talk to Nova → She collects your name, date/time, and title → Confirms availability → Books it.**

---

## 🎙️ For Users: How to Talk to Nova

If someone has sent you a link to Nova (e.g. `https://YOUR_USERNAME.github.io/voice-scheduling-agent/`), here is how to use it:

1. **Open the Link**: Open the URL in any modern browser.
2. **Start the Call**: Click the large "Start Call" button.
3. **Allow Microphone**: Your browser will ask for microphone permissions. Allow it so Nova can hear you.
4. **Speak Naturally**: 
   - Nova will greet you and ask for your name.
   - Tell her what day and time works for you. Nova automatically detects your local timezone, so saying *"Tomorrow at 3pm"* works perfectly!
   - You can optionally provide a meeting title, like *"Let's schedule a Sync regarding the new project for next Tuesday at 10 AM."*
5. **Confirmation**: Nova will read back the details. Once you say "Yes", the meeting is instantly booked on the calendar!

---

## 🛠️ For Deployers: Run Your Own Instance

Want to deploy your own Nova assistant? Our architecture ensures a seamless, enterprise-grade experience.

### Architecture & Features
* **Voice Orchestrator**: [Vapi.ai](https://vapi.ai) handles WebRTC, Voice Activity Detection, interruptions, and streaming.
* **LLM**: Groq (Llama 3.3 70B) for ultra-low latency conversational intelligence.
* **Serverless Calendar Auth**: Uses Google Service Accounts, so there is no clunky OAuth login screen for your users.
* **Timezone Injection**: The frontend detects the caller's timezone and passes it to the agent so times are always resolved accurately.
* **Race Condition Protection**: The backend silently re-checks your calendar availability milliseconds before booking to prevent double-booking.
* **Webhook Security**: Webhooks are cryptographically verified using `x-vapi-secret` to prevent API spam.

### Prerequisites
1. Python 3.10+
2. A [Vapi account](https://vapi.ai) ($10 free credit included)
3. A Google Cloud project with the **Google Calendar API** enabled.

---

### Step 1: Get Your Credentials

You need exactly three things before running the setup script:

1. **Vapi Private API Key**: Found in your Vapi Dashboard → Keys.
2. **Vapi Public Key**: Found in the same dashboard.
3. **Google Service Account JSON**:
   - Go to Google Cloud Console → APIs & Services → Credentials.
   - Create a **Service Account** (name it `voice-scheduler`).
   - Click the new account → Keys → Add Key → JSON. Save this file to your computer.
   - **Crucial**: Go to your personal Google Calendar settings, find "Share with specific people", and share your calendar with the Service Account email address, giving it **"Make changes to events"** permission.

### Step 2: Initialize the Project

We have built an initialization script that handles 100% of the busywork. It registers your assistant with Vapi, configures secure webhooks, safely moves your Google credentials, and injects your keys into the frontend!

```bash
git clone https://github.com/YOUR_USERNAME/voice-scheduling-agent.git
cd voice-scheduling-agent
python init.py
```
Follow the interactive prompts in the terminal.

### Step 3: Test on Your Computer (Local Run)

Before putting Nova on the public internet, you can run her directly on your laptop to ensure everything works. Note: *Nova will only work while your terminal is open.*

**1. Start the Backend:**
```bash
cd backend
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

**2. Expose to the Internet (for Vapi):**
Vapi needs to be able to reach your laptop. Run ngrok in a new terminal window:
```bash
ngrok http 8000
```
*Note: If you didn't provide your ngrok URL during `init.py`, you will need to manually update the `serverUrl` in your Vapi dashboard to your new `https://xxx.ngrok-free.app/vapi/webhook` URL.*

**3. Open the Frontend:**
Simply double-click `frontend/index.html` to open it in your browser. Click "Start Call" and talk to Nova!

---

## 🚀 Step 4: Put it on the Internet 24/7 (Deployment)

Once you are happy with how Nova works locally, you can deploy her so she is available to anyone in the world, 24/7, even when your computer is turned off.

### 1. Backend (Render / Railway)
1. Push your code repository to GitHub.
2. Log into [render.com](https://render.com) and create a **New Web Service**.
3. Connect your GitHub repository and use these settings:
   - **Root Directory**: `backend`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. **Environment Variables**:
   - Copy all the variables from your local `.env` file into Render's environment variables.
   - For `GOOGLE_SERVICE_ACCOUNT_JSON`, paste the entire raw contents of your JSON file as a single string.
5. **Update Vapi**: Once Render gives you a live URL (e.g., `https://nova.onrender.com`), go to your Vapi dashboard and update your assistant's `serverUrl` to `https://nova.onrender.com/vapi/webhook`.

### 2. Frontend (GitHub Pages)
1. In your GitHub repository settings, go to **Pages**.
2. Under "Build and deployment", set Source to **Deploy from branch**.
3. Select the `main` branch and the `/frontend` folder.
4. Save. Your agent is now live permanently at `https://YOUR_USERNAME.github.io/voice-scheduling-agent/`!

---

## ⚙️ Advanced Configuration

### Checking Multiple Calendars
During the `python init.py` setup, you will be asked which calendars Nova should check for conflicts. You can provide a comma-separated list of calendar emails (e.g. `primary, work@company.com, family@group.calendar.google.com`).

Nova will check **all** listed calendars for conflicts before confirming availability, preventing double-booking across your personal and work lives! *Note: The actual event will always be booked onto the first calendar in the list.*

If you ever need to change these calendars after setup, simply edit the `GOOGLE_CALENDAR_ID` variable in your `.env` file.

### Webhook Security
During setup, `init.py` generated a cryptographically secure `VAPI_WEBHOOK_SECRET` and registered it with your Vapi assistant. Your backend (`main.py`) validates this secret on every incoming request. If an attacker discovers your backend URL and tries to send fake meeting requests, the server will block them with a `401 Unauthorized` response.
