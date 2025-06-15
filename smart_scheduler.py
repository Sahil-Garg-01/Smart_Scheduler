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
WORKDAY_START_HOUR = 9
WORKDAY_END_HOUR = 17
TIME_PREFERENCES = {
    "morning": (9, 12),
    "afternoon": (12, 17),
    "evening": (17, 20)
}

# Load API Key
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GOOGLE_API_KEY:
    raise ValueError("GOOGLE_API_KEY not found in .env file")
genai.configure(api_key=GOOGLE_API_KEY)

# Initialize Gemini AI chat
try:
    chat_model = genai.GenerativeModel("gemini-1.5-flash")
    chat = chat_model.start_chat(history=[])
except Exception as e:
    raise RuntimeError(f"Failed to initialize Gemini AI: {e}")

# Google Calendar setup
creds = None
if os.path.exists("token.json"):
    try:
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    except Exception as e:
        print(f"Invalid token.json: {e}. Delete it and try again.")
if not creds or not creds.valid:
    if not os.path.exists(CLIENT_SECRETS_FILE):
        raise FileNotFoundError("Missing credentials.json")
    try:
        flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
        creds = flow.run_local_server(port=0)
        with open("token.json", "w") as token:
            token.write(creds.to_json())
    except Exception as e:
        raise RuntimeError(f"Failed to authenticate with Google Calendar: {e}")
calendar_service = build("calendar", "v3", credentials=creds)

conversation = {"duration": None, "day": None, "time": None, "title": None, "attendees": None}

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
        speak_text("Failed to record audio. Please try again.")
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
        return None
    except sr.RequestError as e:
        print(f"Speech recognition error: {e}")
        speak_text("Speech recognition failed. Please try again.")
        return None

# Calendar Operations
def get_day(day_str):
    """Parse a day string into a datetime object."""
    if not day_str:
        return None
    today = datetime.datetime.now(pytz.UTC)
    day_map = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
               "friday": 4, "saturday": 5, "sunday": 6}
    day_str = day_str.lower()
    if "today" in day_str:
        return today
    if "tomorrow" in day_str:
        return today + datetime.timedelta(days=1)
    if "next week" in day_str:
        today += datetime.timedelta(days=7)
        day_str = day_str.replace("next week", "").strip()
    if "next" in day_str:
        for day in day_map:
            if day in day_str:
                days_ahead = (day_map[day] - today.weekday() + 7) % 7 or 7
                return today + datetime.timedelta(days=days_ahead)
    for day, offset in day_map.items():
        if day in day_str:
            days_ahead = (offset - today.weekday() + 7) % 7
            return today + datetime.timedelta(days=days_ahead)
    try:
        return datetime.datetime.strptime(day_str, "%B %d").replace(year=today.year, tzinfo=pytz.UTC)
    except:
        return None

def check_calendar(start_time, end_time, duration):
    """Check for events in the given time range."""
    try:
        start_time = start_time.astimezone(pytz.UTC)
        end_time = end_time.astimezone(pytz.UTC)
        events_result = calendar_service.events().list(
            calendarId="primary",
            timeMin=start_time.isoformat(),
            timeMax=end_time.isoformat(),
            singleEvents=True,
            orderBy="startTime"
        ).execute()
        return events_result.get("items", [])
    except HttpError as error:
        print(f"Calendar error: {error}")
        speak_text("Failed to access calendar. Please try again.")
        return []

def create_event(start_time, duration, title, attendees=None):
    """Create a Google Calendar event with optional attendees."""
    try:
        event = {
            "summary": title or "Meeting",
            "start": {"dateTime": start_time.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": (start_time + datetime.timedelta(minutes=duration)).isoformat(), "timeZone": "UTC"}
        }
        if attendees:
            event["attendees"] = [{"email": email.strip()} for email in attendees.split(",") if email.strip()]
        created = calendar_service.events().insert(calendarId="primary", body=event).execute()
        summary = chat.send_message(
            f"Create a friendly sentence confirming this event: {title} at {start_time.strftime('%I:%M %p')} on {start_time.strftime('%A')}"
        ).text
        return summary + f"\nEvent link: {created.get('htmlLink')}"
    except HttpError as error:
        print(f"Event creation error: {error}")
        return f"Failed to create event: {error}"

def list_events_today():
    """List all events scheduled for today."""
    now = datetime.datetime.utcnow().replace(tzinfo=pytz.UTC)
    end = now.replace(hour=23, minute=59)
    events = check_calendar(now, end, 1)
    if not events:
        return "You have no events scheduled for today."
    response = "Today's meetings:\n"
    for e in events:
        start_time = e['start'].get('dateTime', '')
        time = datetime.datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        response += f"- {e['summary']} at {time.strftime('%I:%M %p')}\n"
    return response.strip()

def cancel_meeting_at(time_str):
    """Cancel a meeting at the specified time within the next week."""
    now = datetime.datetime.utcnow().replace(tzinfo=pytz.UTC)
    end = now + datetime.timedelta(days=7)
    events = check_calendar(now, end, 1)
    for e in events:
        start_time = e['start'].get('dateTime', '')
        event_time = datetime.datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        if time_str in event_time.strftime("%I:%M %p"):
            try:
                calendar_service.events().delete(calendarId='primary', eventId=e['id']).execute()
                return f"Cancelled meeting '{e['summary']}' at {time_str}."
            except HttpError as error:
                print(f"Event deletion error: {error}")
                return f"Failed to cancel meeting: {error}"
    return "No meeting found at that time to cancel."

def free_slots_for_day(day_str, duration=DEFAULT_DURATION):
    """Find free time slots for a given day and duration."""
    day = get_day(day_str)
    if not day:
        return f"Could not understand the day: {day_str}."
    start_hour = WORKDAY_START_HOUR
    end_hour = WORKDAY_END_HOUR
    if conversation.get("time"):
        for pref, (start, end) in TIME_PREFERENCES.items():
            if pref in conversation["time"].lower():
                start_hour, end_hour = start, end
                break
    start_time = day.replace(hour=start_hour, minute=0, tzinfo=pytz.UTC)
    end_time = day.replace(hour=end_hour, minute=0, tzinfo=pytz.UTC)
    events = check_calendar(start_time, end_time, duration)
    busy = [(datetime.datetime.fromisoformat(e['start']['dateTime'].replace("Z", "+00:00")),
             datetime.datetime.fromisoformat(e['end']['dateTime'].replace("Z", "+00:00"))) for e in events]
    free_slots = []
    current = start_time
    while current + datetime.timedelta(minutes=duration) <= end_time:
        slot_end = current + datetime.timedelta(minutes=duration)
        if all(current >= b[1] or slot_end <= b[0] for b in busy):
            free_slots.append(f"{current.strftime('%I:%M %p')} to {slot_end.strftime('%I:%M %p')}")
        current += datetime.timedelta(minutes=30)
    if free_slots:
        return f"Free slots on {day_str} for {duration} minutes: {', '.join(free_slots[:2])}"
    next_day = day + datetime.timedelta(days=1)
    return f"No free slots on {day_str}. Try {next_day.strftime('%A')}?"

# NLP and Scheduling
def parse_duration(text):
    """Extract duration from text in minutes."""
    if not text:
        return None
    duration_match = re.search(r'(\d+)\s*(minutes?|mins?|hours?|hrs?)', text.lower())
    if duration_match:
        value = int(duration_match.group(1))
        unit = duration_match.group(2).lower()
        return value if 'min' in unit else value * 60
    return None

def parse_time(text):
    """Extract time from text."""
    if not text:
        return None
    text = text.lower().strip()
    time_match = re.search(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)?|(\d{1,2})\s*(o\'?clock)\s*(am|pm)?', text)
    if time_match:
        hour = int(time_match.group(1) or time_match.group(4))
        minute = int(time_match.group(2) or 0)
        period = time_match.group(3) or time_match.group(6)
        if period == "pm" and hour != 12:
            hour += 12
        elif period == "am" and hour == 12:
            hour = 0
        return f"{hour:02d}:{minute:02d}"
    for pref in TIME_PREFERENCES:
        if pref in text:
            return pref
    return None

def parse_attendees(text):
    """Extract email addresses from text."""
    if not text:
        return None
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    emails = re.findall(email_pattern, text)
    return ", ".join(emails) if emails else None

def parse_meeting_info(transcription):
    """Extract meeting details using regex and Gemini AI chat."""
    if not transcription:
        return {}
    info = {
        "title": None,
        "meeting_duration": None,
        "preferred_day": None,
        "preferred_time": None,
        "attendees": None
    }
    text = transcription.lower()
    # Regex-based parsing
    info["meeting_duration"] = parse_duration(text)
    info["preferred_time"] = parse_time(text)
    day_match = re.search(r'(next\s+week\s+)?(?:on\s+)?(next\s+)?(\w+day|\w+)|today|tomorrow', text)
    if day_match:
        info["preferred_day"] = day_match.group(0).replace("on ", "").strip()
    info["attendees"] = parse_attendees(transcription)
    title_match = re.search(r'(?:called|about|regarding|with)\s+([a-zA-Z0-9 ]+)', text)
    if title_match:
        info["title"] = title_match.group(1).strip()
    # Gemini AI fallback
    if not all([info["title"], info["meeting_duration"], info["preferred_day"], info["preferred_time"]]):
        try:
            prompt = f"""
            Extract meeting details from: '{transcription}'. Return JSON:
            ```json
            {{
                "title": <text or null>,
                "meeting_duration": <number or null>,
                "preferred_day": <text or null>,
                "preferred_time": <text or null>,
                "attendees": <text or null>
            }}
            ```
            """
            response = chat.send_message(prompt)
            gemini_info = json.loads(response.text.strip("```json\n").strip("\n```"))
            info["title"] = info["title"] or gemini_info.get("title")
            info["meeting_duration"] = info["meeting_duration"] or parse_duration(gemini_info.get("meeting_duration", ""))
            info["preferred_day"] = info["preferred_day"] or gemini_info.get("preferred_day")
            info["preferred_time"] = info["preferred_time"] or parse_time(gemini_info.get("preferred_time", ""))
            info["attendees"] = info["attendees"] or gemini_info.get("attendees")
        except:
            info["title"] = info["title"] or transcription.strip()
    return info

def process_scheduling():
    """Process and schedule a meeting based on conversation data."""
    try:
        day = get_day(conversation["day"])
        if not day:
            return "Sorry, I couldn't understand the day."
        duration = int(conversation["duration"] or DEFAULT_DURATION)
        start_hour = WORKDAY_START_HOUR
        if conversation["time"]:
            time_str = parse_time(conversation["time"])
            if time_str in TIME_PREFERENCES:
                start_hour = TIME_PREFERENCES[time_str][0]
                start_time = day.replace(hour=start_hour, minute=0, tzinfo=pytz.UTC)
                end_time = day.replace(hour=TIME_PREFERENCES[time_str][1], minute=0, tzinfo=pytz.UTC)
                free_slots = free_slots_for_day(conversation["day"], duration)
                if "No free slots" in free_slots:
                    return free_slots
                return f"Please choose a slot: {free_slots}"
            else:
                try:
                    time_obj = datetime.datetime.strptime(time_str, "%H:%M")
                    start_time = day.replace(hour=time_obj.hour, minute=time_obj.minute, tzinfo=pytz.UTC)
                except ValueError:
                    return "Sorry, I couldn't understand the time."
        else:
            start_time = day.replace(hour=start_hour, minute=0, tzinfo=pytz.UTC)
        end_time = start_time + datetime.timedelta(minutes=duration)
        events = check_calendar(start_time, end_time, duration)
        if events:
            return "There is already a meeting scheduled at that time."
        return create_event(start_time, duration, conversation["title"], conversation["attendees"])
    except ValueError as e:
        return f"Invalid input: {e}"
    except Exception as e:
        return f"Failed to schedule meeting: {e}"

def reset_conversation():
    """Reset the conversation dictionary."""
    global conversation
    conversation = {"duration": None, "day": None, "time": None, "title": None, "attendees": None}

# Main Loop
def get_voice_confirmation():
    """Get yes/no confirmation via voice."""
    speak_text("Please say yes or no.")
    audio_bytes = record_audio()
    response = transcribe_audio(audio_bytes)
    if response:
        response = response.lower().strip()
        if "yes" in response:
            return "yes"
        elif "no" in response:
            return "no"
    return "unknown"

def is_conversation_complete():
    """Check if all required conversation fields are filled."""
    return all([
        conversation.get("title"),
        conversation.get("duration"),
        conversation.get("day"),
        conversation.get("time")
    ])

def main():
    """Main loop for the AI Scheduler."""
    print("🔊 AI Scheduler v3 Ready — Type 'voice' for speech, 'text' for typing, 'exit' to quit.")
    while True:
        cmd = input("> ").strip().lower()
        if cmd == "exit":
            speak_text("Goodbye!")
            break
        user_input = None
        if cmd == "voice":
            audio_bytes = record_audio()
            user_input = transcribe_audio(audio_bytes)
            if not user_input:
                speak_text("Sorry, I didn't catch that. Please try again.")
                continue
        elif cmd == "text":
            user_input = input("You: ").strip()
        else:
            print("Say 'voice', 'text', or 'exit'.")
            continue
        reset_conversation()
        lower = user_input.lower()
        if "what are my meetings today" in lower:
            response = list_events_today()
            print(f"🤖 {response}")
            speak_text(response)
            continue
        if "cancel" in lower and "meeting" in lower:
            time_part = lower.split("at")[-1].strip()
            response = cancel_meeting_at(time_part)
            print(f"🤖 {response}")
            speak_text(response)
            continue
        if "free slots" in lower or "availability" in lower:
            info = parse_meeting_info(user_input)
            day_word = info.get("preferred_day", lower.split("for")[-1].strip())
            duration = info.get("meeting_duration")
            if not duration:
                speak_text("How long should the meeting be?")
                duration_response = transcribe_audio(record_audio()) if cmd == "voice" else input("You: ").strip()
                duration = parse_duration(duration_response) or DEFAULT_DURATION
            response = free_slots_for_day(day_word, duration)
            print(f"🤖 {response}")
            speak_text(response)
            continue
        info = parse_meeting_info(user_input)
        conversation.update({
            "title": info.get("title"),
            "duration": info.get("meeting_duration"),
            "day": info.get("preferred_day"),
            "time": info.get("preferred_time"),
            "attendees": info.get("attendees")
        })
        while not is_conversation_complete():
            if not conversation["title"]:
                speak_text("What should I call this meeting?")
                conversation["title"] = transcribe_audio(record_audio()) if cmd == "voice" else input("You: ").strip()
            if not conversation["duration"]:
                speak_text("How long should the meeting be?")
                duration_response = transcribe_audio(record_audio()) if cmd == "voice" else input("You: ").strip()
                conversation["duration"] = parse_duration(duration_response) or conversation["duration"]
            if not conversation["day"]:
                speak_text("Which day should I schedule it?")
                conversation["day"] = transcribe_audio(record_audio()) if cmd == "voice" else input("You: ").strip()
            if not conversation["time"]:
                speak_text("What time should I schedule it?")
                time_response = transcribe_audio(record_audio()) if cmd == "voice" else input("You: ").strip()
                conversation["time"] = parse_time(time_response) or conversation["time"]
        if not conversation["attendees"]:
            speak_text("Who should I invite to this meeting? Say email addresses or none.")
            attendees_response = transcribe_audio(record_audio()) if cmd == "voice" else input("You: ").strip()
            conversation["attendees"] = parse_attendees(attendees_response)
        attendees_text = f" with attendees {conversation['attendees']}" if conversation["attendees"] else ""
        confirmation_text = f"You're scheduling '{conversation['title']}' at {conversation['time']} for {conversation['duration']} minutes{attendees_text}. Should I go ahead?"
        print(f"🤖 {confirmation_text}")
        speak_text(confirmation_text)
        confirmation = get_voice_confirmation() if cmd == "voice" else input("You (yes/no): ").strip().lower()
        if confirmation == "yes":
            speak_text("Your meeting has been scheduled successfully.")
            reset_conversation()
        elif confirmation == "no":
            speak_text("Okay, I won’t schedule it.")
        else:
            speak_text("Sorry, I couldn't understand your confirmation. Please try again.")
        reset_conversation()

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Oops! Something broke: {e}")
        speak_text("Something went wrong. Please try again.")