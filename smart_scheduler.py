# Configuration
import os
import datetime
import pytz
import json
import re
import pyaudio
import wave
import io
import speech_recognition as sr
import google.generativeai as genai
import pyttsx3
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from dotenv import load_dotenv

# Constants
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
CHUNK = 1024
RECORD_SECONDS = 5
SCOPES = ["https://www.googleapis.com/auth/calendar"]
CLIENT_SECRETS_FILE = "credentials.json"
DEFAULT_DURATION = 30

# Load the API key from a .env file
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GOOGLE_API_KEY:
    print("Error: Please add your GOOGLE_API_KEY to a .env file.")
    exit()

# Set up the Gemini AI model for chatting
try:
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel("gemini-1.5-flash")
    chat = model.start_chat(history=[])
except Exception:
    print("Error: Could not connect to Gemini AI. Check your API key.")
    exit()

# Set up Google Calendar API
creds = None
if os.path.exists("token.json"):
    try:
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    except Exception:
        print("Error: Problem with token.json file. Try deleting it and re-authenticating.")

if not creds or not creds.valid:
    if not os.path.exists(CLIENT_SECRETS_FILE):
        print(
            "Error: Missing credentials.json. Download it from Google Cloud Console "
            "(https://console.cloud.google.com/apis/credentials) and place it in this folder."
        )
        exit()
    try:
        flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
        creds = flow.run_local_server(port=0)
        with open("token.json", "w") as token:
            token.write(creds.to_json())
    except Exception:
        print("Error: Could not log in to Google Calendar. Check your setup.")
        exit()

try:
    calendar_service = build("calendar", "v3", credentials=creds)
except Exception:
    print("Error: Could not connect to Google Calendar.")
    exit()

# Store conversation details
conversation = {
    "duration": None,  # How long the meeting is (in minutes)
    "day": None,       # Which day (e.g., "Tuesday")
    "time": None,      # Preferred time (e.g., "afternoon" or "2 PM")
    "title": None      # Meeting title
}

# Audio Processing
def speak_text(text):
    """Speak the given text using text-to-speech."""
    try:
        engine = pyttsx3.init()
        engine.setProperty('rate', 175)
        engine.say(text)
        engine.runAndWait()
        return True
    except Exception as e:
        print(f"Speech error: {e}")
        return False

def record_audio():
    """Record audio for a fixed duration and return as BytesIO."""
    try:
        audio = pyaudio.PyAudio()
        stream = audio.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)
        print("🎙️ Recording... (5 seconds)")
        frames = [stream.read(CHUNK, exception_on_overflow=False) for _ in range(0, int(RATE / CHUNK * RECORD_SECONDS))]
        stream.stop_stream()
        stream.close()
        audio.terminate()
        wav_io = io.BytesIO()
        wf = wave.open(wav_io, 'wb')
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(audio.get_sample_size(FORMAT))
        wf.setframerate(RATE)
        wf.writeframes(b''.join(frames))
        wf.close()
        wav_io.seek(0)
        return wav_io
    except Exception as e:
        print(f"Audio recording error: {e}")
        speak_text("Failed to record audio.")
        return None

def transcribe_audio(audio_bytes_io):
    """Transcribe audio to text using Google Speech Recognition."""
    if not audio_bytes_io:
        return None
    try:
        recognizer = sr.Recognizer()
        with sr.AudioFile(audio_bytes_io) as source:
            audio = recognizer.record(source)
            return recognizer.recognize_google(audio)
    except sr.UnknownValueError:
        speak_text("Sorry, I couldn't understand that. Please try again.")
        return None
    except sr.RequestError as e:
        print(f"Speech recognition error: {e}")
        speak_text("Speech recognition failed.")
        return None

def parse_time(text):
    """Extract specific time from text (e.g., '2 PM' -> '14:00')."""
    if not text:
        return None
    text = text.lower().strip()
    time_match = re.search(
        r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)?|(\d{1,2})\s*(o\'?clock)\s*(am|pm)?|\b(noon|midnight)\b',
        text
    )
    if time_match:
        if time_match.group(7):  # Handle 'noon' or 'midnight'
            hour = 12 if time_match.group(7) == "noon" else 0
            minute = 0
            return f"{hour:02d}:{minute:02d}"
        hour = int(time_match.group(1) or time_match.group(4))
        minute = int(time_match.group(2) or 0)
        period = time_match.group(3) or time_match.group(6)
        if period == "pm" and hour != 12:
            hour += 12
        elif period == "am" and hour == 12:
            hour = 0
        return f"{hour:02d}:{minute:02d}"
    return None

# Calendar Operations
def check_calendar(start_time, end_time, duration):
    """Check for available time slots, returning list of (start, end) tuples."""
    try:
        start_time = start_time.astimezone(pytz.UTC)
        end_time = end_time.astimezone(pytz.UTC)
        events_result = calendar_service.events().list(
            calendarId='primary',
            timeMin=start_time.isoformat(),
            timeMax=end_time.isoformat(),
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])
        free_slots = []
        current_time = start_time
        while current_time + datetime.timedelta(minutes=duration) <= end_time:
            slot_end = current_time + datetime.timedelta(minutes=duration)
            is_free = True
            for event in events:
                event_start = datetime.datetime.fromisoformat(event['start'].get('dateTime').replace('Z', '')).replace(tzinfo=pytz.UTC)
                event_end = datetime.datetime.fromisoformat(event['end'].get('dateTime').replace('Z', '')).replace(tzinfo=pytz.UTC)
                if not (slot_end <= event_start or current_time >= event_end):
                    is_free = False
                    break
            if is_free:
                free_slots.append((current_time, slot_end))
            current_time += datetime.timedelta(minutes=30)
        return free_slots, events
    except HttpError as e:
        print(f"Error: Could not access Google Calendar: {e}")
        speak_text("Failed to check calendar.")
        return [], []  # Return empty lists instead of None
    except Exception as e:
        print(f"Unexpected error: {e}")
        speak_text("Something went wrong.")
        return [], []  # Return empty lists instead of None

def create_event(start_time, duration, title):
    """Create a Google Calendar event."""
    try:
        event = {
            "summary": title or "Meeting",
            "start": {"dateTime": start_time.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": (start_time + datetime.timedelta(minutes=duration)).isoformat(), "timeZone": "UTC"}
        }
        created = calendar_service.events().insert(calendarId="primary", body=event).execute()
        return created
    except HttpError as error:
        print(f"Error creating event: {error}")
        return None
    except Exception as e:
        print(f"Unexpected error creating event: {e}")
        return None

def list_events_today():
    """List all events scheduled for today."""
    now = datetime.datetime.now(pytz.UTC)
    start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_time = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    _, events = check_calendar(start_time, end_time, 1)
    return [
        {
            "title": e["summary"],
            "start": datetime.datetime.fromisoformat(e["start"].get("dateTime").replace("Z", "")).strftime("%I:%M %p"),
            "end": datetime.datetime.fromisoformat(e["end"].get("dateTime").replace("Z", "")).strftime("%I:%M %p")
        }
        for e in events
    ]

def cancel_meeting_at(time_str):
    """Cancel a meeting at the specified time within the next week."""
    time = parse_time(time_str)
    if not time:
        return []
    now = datetime.datetime.now(pytz.UTC)
    start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_time = now + datetime.timedelta(days=7)
    _, events = check_calendar(start_time, end_time, 1)
    cancelled = []
    try:
        time_obj = datetime.datetime.strptime(time, "%H:%M")
        for e in events:
            event_start = datetime.datetime.fromisoformat(e["start"].get("dateTime").replace("Z", "")).replace(tzinfo=pytz.UTC)
            if event_start.strftime("%H:%M") == time_obj.strftime("%H:%M"):
                calendar_service.events().delete(calendarId="primary", eventId=e["id"]).execute()
                cancelled.append({
                    "title": e["summary"],
                    "start": event_start.strftime("%I:%M %p")
                })
        return cancelled
    except HttpError as error:
        print(f"Error deleting event: {error}")
        return None
    except Exception as e:
        print(f"Unexpected error deleting event: {e}")
        return None

def free_slots_for_day(day_str, duration=DEFAULT_DURATION):
    """Find free slots for a given day."""
    target_day = get_day(day_str)
    if not target_day:
        return None
    start_time = target_day.replace(hour=9, minute=0, second=0, microsecond=0, tzinfo=pytz.UTC)
    end_time = target_day.replace(hour=17, minute=0, second=0, microsecond=0, tzinfo=pytz.UTC)
    if conversation.get("time"):
        if "afternoon" in conversation["time"].lower():
            start_time = target_day.replace(hour=12, minute=0, tzinfo=pytz.UTC)
        elif "morning" in conversation["time"].lower():
            start_time = target_day.replace(hour=9, minute=0, tzinfo=pytz.UTC)
        elif "evening" in conversation["time"].lower():
            start_time = target_day.replace(hour=17, minute=0, tzinfo=pytz.UTC)
        elif parse_time(conversation["time"]):
            time = parse_time(conversation["time"])
            time_obj = datetime.datetime.strptime(time, "%H:%M")
            start_time = target_day.replace(hour=time_obj.hour, minute=time_obj.minute, tzinfo=pytz.UTC)
            end_time = start_time + datetime.timedelta(hours=1)
    free_slots, _ = check_calendar(start_time, end_time, duration)
    return [
        {
            "start": slot[0].strftime("%I:%M %p"),
            "end": slot[1].strftime("%I:%M %p")
        }
        for slot in free_slots
    ] if free_slots else None

# Function to understand what the user said
def understand_input(user_input):
    prompt = f"""
    You are a scheduling helper. From this input, find:
    - Meeting duration (e.g., '1 hour' = 60 minutes)
    - Preferred day (e.g., 'Tuesday' or 'June 20th')
    - Preferred time (e.g., 'afternoon' or '2 PM')
    - Meeting title (e.g., 'team sync')
    If something is missing, use null.
    Input: "{user_input}"
    Return JSON like this:
    ```json
    {{
        "meeting_duration": <number or null>,
        "preferred_day": <text or null>,
        "preferred_time": <text or null>,
        "title": <text or null>
    }}
    ```
    """
    try:
        response = chat.send_message(prompt)
        return json.loads(response.text.strip("```json\n").strip("\n```"))
    except Exception as e:
        print(f"Error: Could not understand your input: {e}")
        speak_text("Sorry, I couldn't understand that.")
        return {"meeting_duration": None, "preferred_day": None, "preferred_time": None, "title": None}

# Function to reply to the user
def make_reply(user_input, free_slots=None, events=None, cancelled=None, event_created=None):
    current_state = f"Duration: {conversation['duration']}, Day: {conversation['day']}, Time: {conversation['time']}, Title: {conversation['title']}"
    slots_info = [{"start": slot[0].strftime("%I:%M %p"), "end": slot[1].strftime("%I:%M %p")} for slot in free_slots] if free_slots else None
    events_info = [{"title": e["summary"], "start": datetime.datetime.fromisoformat(e["start"].get("dateTime").replace("Z", "")).strftime("%I:%M %p"), "end": datetime.datetime.fromisoformat(e["end"].get("dateTime").replace("Z", "")).strftime("%I:%M %p")} for e in events]
    cancelled_info =[{"title": c["title"], "start": c["start"]} for c in cancelled]
    event_created_info = f"Event created: {event_created['summary']} at {event_created['start']['dateTime']}" if event_created else "No event created."
    prompt = f"""
    You are a friendly scheduling bot. Generate a natural, concise response based on the user input and state.
    - For scheduling: Confirm details or ask for missing info (duration, day, time, title).
    - For free slots: Suggest the first two slots or another day if none.
    - For events today: List events or say none.
    - For cancellations: Confirm cancellation or say none found.
    - Use friendly language (e.g., "Got it! I'll schedule your team sync at 2 PM Tuesday").
    User input: "{user_input}"
    State: {current_state}
    Slots: {slots_info}
    Events: {events_info}
    Cancelled: {cancelled_info}
    Event created: {event_created_info}
    """
    try:
        response = chat.send_message(prompt)
        return response.text
    except Exception:
        speak_text("Sorry, something went wrong.")
        return "Sorry, something went wrong."

# Function to figure out which day the user means
def get_day(day_str):
    today = datetime.datetime.now(pytz.UTC)
    day_map = {
        "monday": 0, "tuesday": 1, "wednesday": 2,
        "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6
    }
    day_str = day_str.lower()
    if "today" in day_str:
        return today
    if "tomorrow" in day_str:
        return today + datetime.timedelta(days=1)
    if "next week" in day_str:
        today += datetime.timedelta(days=7)
        day_str = day_str.replace("next week", "").strip()
    for day, offset in day_map.items():
        if day in day_str:
            days_ahead = (offset - today.weekday() + 7) % 7
            return today + datetime.timedelta(days=days_ahead)
    try:
        return datetime.datetime.strptime(day_str, "%B %d").replace(year=today.year, tzinfo=pytz.UTC)
    except:
        return None

# Main program
def main():
    print("🔊 Smart Scheduler: Say something to start scheduling or 'exit' to quit.")
    speak_text("Hello! Let's schedule a meeting.")
    while True:
        audio_bytes = record_audio()
        user_input = transcribe_audio(audio_bytes)
        if not user_input:
            continue
        print(f"🗣️ You said: {user_input}")
        if user_input.lower() in ["exit", "quit"]:
            print("Smart Scheduler: Bye!")
            speak_text("Goodbye!")
            break
        lower_input = user_input.lower()
        # Handle command shortcuts
        if "meetings today" in lower_input:
            events = list_events_today()
            reply = make_reply(user_input, events=events)
            print(f"🤖 Smart Scheduler: {reply}")
            speak_text(reply)
            continue
        if "cancel" in lower_input and "meeting" in lower_input:
            time_match = re.search(r'\d{1,2}(?::\d{2})?\s*(am|pm)|noon|midnight', lower_input)
            if time_match:
                time_str = time_match.group(0)
                cancelled = cancel_meeting_at(time_str)
                if cancelled is not None:
                    reply = make_reply(user_input, cancelled=cancelled)
                    print(f"🤖 Smart Scheduler: {reply}")
                    speak_text(reply)
                else:
                    reply = make_reply(user_input, cancelled=[])
                    print(f"🤖 Smart Scheduler: {reply}")
                    speak_text("Sorry, I couldn't cancel that meeting.")
                continue
        if "free slots" in lower_input or "availability" in lower_input:
            day_match = re.search(r'(monday|tuesday|wednesday|thursday|friday|saturday|sunday|today|tomorrow|next\s+\w+)', lower_input)
            duration_match = re.search(r'(\d+)\s*(hour|hours|minute|minutes)', lower_input)
            day_str = day_match.group(0) if day_match else None
            duration = int(duration_match.group(1)) * (60 if "hour" in duration_match.group(2) else 1) if duration_match else DEFAULT_DURATION
            if day_str:
                free_slots = free_slots_for_day(day_str, duration)
                reply = make_reply(user_input, free_slots=free_slots if free_slots else [])
                print(f"🤖 Smart Scheduler: {reply}")
                speak_text(reply)
            else:
                reply = make_reply(user_input, free_slots=[])
                print(f"🤖 Smart Scheduler: {reply}")
                speak_text("Please specify a day, like Thursday.")
            continue
        # Handle scheduling
        info = understand_input(user_input)
        if info["meeting_duration"]:
            conversation["duration"] = info["meeting_duration"]
        if info["preferred_day"]:
            conversation["day"] = info["preferred_day"]
        if info["preferred_time"]:
            conversation["time"] = info["preferred_time"]
        if info["title"]:
            conversation["title"] = info["title"]
        if conversation["duration"] and conversation["day"] and conversation["title"] and conversation["time"]:
            target_day = get_day(conversation["day"])
            if target_day:
                start_time = target_day.replace(hour=9, minute=0, second=0, microsecond=0, tzinfo=pytz.UTC)
                end_time = target_day.replace(hour=17, minute=0, second=0, microsecond=0, tzinfo=pytz.UTC)
                if conversation["time"]:
                    time = parse_time(conversation["time"])
                    if time:
                        time_obj = datetime.datetime.strptime(time, "%H:%M")
                        start_time = target_day.replace(hour=time_obj.hour, minute=time_obj.minute, tzinfo=pytz.UTC)
                        end_time = start_time + datetime.timedelta(hours=1)
                    elif "afternoon" in conversation["time"].lower():
                        start_time = target_day.replace(hour=12, minute=0, tzinfo=pytz.UTC)
                    elif "morning" in conversation["time"].lower():
                        start_time = target_day.replace(hour=9, minute=0, tzinfo=pytz.UTC)
                    elif "evening" in conversation["time"].lower():
                        start_time = target_day.replace(hour=17, minute=0, tzinfo=pytz.UTC)
                free_slots, events = check_calendar(start_time, end_time, conversation["duration"])
                if free_slots:  # Check if slots are available
                    event = create_event(free_slots[0][0], conversation["duration"], conversation["title"])
                    if event:
                        reply = make_reply(user_input, event_created=event)
                        print(f"🤖 Smart Scheduler: {reply}")
                        speak_text(reply)
                        conversation.clear()
                    else:
                        reply = make_reply(user_input, free_slots=[{"start": s[0].strftime("%I:%M %p"), "end": s[1].strftime("%I:%M %p")} for s in free_slots[:2]])
                        print(f"🤖 Smart Scheduler: {reply}")
                        speak_text("Sorry, I couldn't create that event.")
                else:
                    next_day = target_day + datetime.timedelta(days=1)
                    reply = make_reply(user_input, free_slots=[{"start": f"No slots on {conversation['day']}", "end": f"Try {next_day.strftime('%A')}?"}])
                    print(f"🤖 Smart Scheduler: {reply}")
                    speak_text(reply)
            else:
                reply = make_reply(user_input, free_slots=[{"start": "Invalid day", "end": "Please specify a valid day like Tuesday."}])
                print(f"🤖 Smart Scheduler: {reply}")
                speak_text(reply)
        else:
            missing = []
            if not conversation["title"]:
                missing.append("title")
            if not conversation["duration"]:
                missing.append("duration")
            if not conversation["day"]:
                missing.append("day")
            if not conversation["time"]:
                missing.append("time")
            reply = make_reply(user_input, free_slots=[{"start": f"Please specify {' and '.join(missing)}", "end": ""}] if missing else [])
            print(f"🤖 Smart Scheduler: {reply}")
            speak_text(reply)
            
# Start the program
if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Oops! Something broke: {e}")
        speak_text("Something went wrong.")