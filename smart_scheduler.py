import os
import datetime
import pytz
import json
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

# Load API Key
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
genai.configure(api_key=GOOGLE_API_KEY)

# Audio settings
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
CHUNK = 1024
RECORD_SECONDS = 5

# Google Calendar setup
SCOPES = ["https://www.googleapis.com/auth/calendar"]
CLIENT_SECRETS_FILE = "credentials.json"
creds = None

if os.path.exists("token.json"):
    try:
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    except:
        print("Invalid token.json. Delete it and try again.")
if not creds or not creds.valid:
    if not os.path.exists(CLIENT_SECRETS_FILE):
        print("Missing credentials.json.")
        exit()
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
    creds = flow.run_local_server(port=0)
    with open("token.json", "w") as token:
        token.write(creds.to_json())

calendar_service = build("calendar", "v3", credentials=creds)

conversation = {"duration": None, "day": None, "time": None, "title": None}


def speak_text(text):
    try:
        engine = pyttsx3.init()
        engine.setProperty('rate', 175)
        engine.say(text)
        engine.runAndWait()
    except Exception as e:
        print(f"Speech error: {e}")


def record_audio():
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


def transcribe_audio(audio_bytes_io):
    recognizer = sr.Recognizer()
    with sr.AudioFile(audio_bytes_io) as source:
        audio = recognizer.record(source)
        try:
            return recognizer.recognize_google(audio)
        except sr.UnknownValueError:
            return None


def ask_gemini(prompt_text):
    model = genai.GenerativeModel("gemini-1.5-flash")
    response = model.generate_content(prompt_text)
    return response.text.strip()


def get_voice_confirmation():
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


def get_day(day_str):
    today = datetime.datetime.now(pytz.UTC)
    day_map = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
               "friday": 4, "saturday": 5, "sunday": 6}
    day_str = day_str.lower()
    for day, offset in day_map.items():
        if day in day_str:
            days_ahead = (offset - today.weekday() + 7) % 7
            return today + datetime.timedelta(days=days_ahead)
    try:
        return datetime.datetime.strptime(day_str, "%B %d").replace(year=today.year, tzinfo=pytz.UTC)
    except:
        return None


def check_calendar(start_time, end_time, duration):
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
        return []


def create_event(start_time, duration, title):
    try:
        event = {
            "summary": title or "Meeting",
            "start": {"dateTime": start_time.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": (start_time + datetime.timedelta(minutes=duration)).isoformat(), "timeZone": "UTC"}
        }
        created = calendar_service.events().insert(calendarId="primary", body=event).execute()
        summary = ask_gemini(f"Create a friendly sentence confirming this event: {title} at {start_time.strftime('%I:%M %p')} on {start_time.strftime('%A')}")
        return summary + f"\nEvent link: {created.get('htmlLink')}"
    except HttpError as error:
        return f"Error: {error}"


def list_events_today():
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
    now = datetime.datetime.utcnow().replace(tzinfo=pytz.UTC)
    end = now + datetime.timedelta(days=7)
    events = check_calendar(now, end, 1)
    for e in events:
        start_time = e['start'].get('dateTime', '')
        event_time = datetime.datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        if time_str in event_time.strftime("%I:%M %p"):
            calendar_service.events().delete(calendarId='primary', eventId=e['id']).execute()
            return f"Cancelled meeting '{e['summary']}' at {time_str}."
    return "No meeting found at that time to cancel."


def free_slots_for_day(day_str):
    duration = 30
    day = get_day(day_str)
    start_time = day.replace(hour=9, minute=0, tzinfo=pytz.UTC)
    end_time = day.replace(hour=17, minute=0, tzinfo=pytz.UTC)
    events = check_calendar(start_time, end_time, duration)
    busy = [(datetime.datetime.fromisoformat(e['start']['dateTime'].replace("Z", "+00:00")),
             datetime.datetime.fromisoformat(e['end']['dateTime'].replace("Z", "+00:00"))) for e in events]
    free_slots = []
    current = start_time
    while current + datetime.timedelta(minutes=duration) <= end_time:
        if all(current >= b[1] or current + datetime.timedelta(minutes=duration) <= b[0] for b in busy):
            free_slots.append(current.strftime("%I:%M %p"))
        current += datetime.timedelta(minutes=30)
    if free_slots:
        return f"Free slots on {day_str}: {', '.join(free_slots)}"
    else:
        return f"No free slots available on {day_str}."
    

def is_conversation_complete():
    return all([
        conversation.get("title"),
        conversation.get("duration"),
        conversation.get("day"),
        conversation.get("time")
    ])

def process_scheduling():
    try:
        # Parse day and time
        day = get_day(conversation["day"])
        if not day:
            return "Sorry, I couldn't understand the day."
        try:
            time_obj = datetime.datetime.strptime(conversation["time"], "%I:%M %p")
        except ValueError:
            try:
                time_obj = datetime.datetime.strptime(conversation["time"], "%H:%M")
            except ValueError:
                return "Sorry, I couldn't understand the time."
        start_time = day.replace(hour=time_obj.hour, minute=time_obj.minute, second=0, microsecond=0, tzinfo=pytz.UTC)
        duration = int(conversation["duration"])
        # Check for conflicts
        end_time = start_time + datetime.timedelta(minutes=duration)
        events = check_calendar(start_time, end_time, duration)
        if events:
            return "There is already a meeting scheduled at that time."
        # Create event
        return create_event(start_time, duration, conversation["title"])
    except Exception as e:
        return f"Failed to schedule meeting: {e}"


def parse_meeting_info(transcription):
    """
    Extracts meeting title, duration, preferred day, and preferred time from the transcription text.
    This is a simple implementation; you may want to improve it with NLP for better accuracy.
    """
    info = {
        "title": None,
        "meeting_duration": None,
        "preferred_day": None,
        "preferred_time": None
    }
    text = transcription.lower()
    # Extract duration (e.g., "for 30 minutes")
    import re
    duration_match = re.search(r'(\d+)\s*(minutes|minute|mins|min)', text)
    if duration_match:
        info["meeting_duration"] = duration_match.group(1)
    # Extract time (e.g., "at 2 pm" or "at 14:00")
    time_match = re.search(r'at\s+(\d{1,2}(:\d{2})?\s*(am|pm)?)', text)
    if time_match:
        info["preferred_time"] = time_match.group(1)
    # Extract day (e.g., "on Monday" or "tomorrow")
    day_match = re.search(r'on\s+(\w+day|\w+)', text)
    if day_match:
        info["preferred_day"] = day_match.group(1)
    elif "tomorrow" in text:
        info["preferred_day"] = "tomorrow"
    elif "today" in text:
        info["preferred_day"] = "today"
    # Extract title (e.g., "meeting about project X")
    title_match = re.search(r'(?:called|about|regarding)\s+([a-zA-Z0-9 ]+)', text)
    if title_match:
        info["title"] = title_match.group(1).strip()
    else:
        # fallback: use the whole transcription as title if nothing else
        info["title"] = transcription.strip()
    return info

def main():
    print("🔊 AI Scheduler Ready — Type 'voice' to speak, 'exit' to quit.")
    while True:
        cmd = input("> ").strip().lower()
        if cmd == "exit":
            speak_text("Goodbye!")
            break
        if cmd == "voice":
            audio_bytes = record_audio()
            transcription = transcribe_audio(audio_bytes)
            if not transcription:
                speak_text("Sorry, I didn't catch that. Please try again.")
                continue
            print(f"🗣️ You said: {transcription}")

            # Check for command shortcuts
            lower = transcription.lower()
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
                day_word = lower.split("for")[-1].strip()
                response = free_slots_for_day(day_word)
                print(f"🤖 {response}")
                speak_text(response)
                continue

            speak_text("You said: " + transcription)
            info = parse_meeting_info(transcription)
            conversation.update({
                "title": info.get("title"),
                "duration": info.get("meeting_duration"),
                "day": info.get("preferred_day"),
                "time": info.get("preferred_time")
            })

            while not is_conversation_complete():
                if not conversation["title"]:
                    speak_text("What should I call this meeting?")
                    conversation["title"] = transcribe_audio(record_audio())
                if not conversation["duration"]:
                    speak_text("How long should the meeting be?")
                    try:
                        duration_response = transcribe_audio(record_audio())
                        conversation["duration"] = int(''.join(filter(str.isdigit, duration_response)))
                    except:
                        conversation["duration"] = None
                if not conversation["day"]:
                    speak_text("Which day should I schedule it?")
                    conversation["day"] = transcribe_audio(record_audio())
                if not conversation["time"]:
                    speak_text("What time should I schedule it?")
                    conversation["time"] = transcribe_audio(record_audio())

            confirmation_text = f"You're scheduling '{conversation['title']}' on {conversation['day']} at {conversation['time']} for {conversation['duration']} minutes. Should I go ahead?"
            print(f"🤖 {confirmation_text}")
            speak_text(confirmation_text)
            confirmation = get_voice_confirmation()
            if confirmation == "yes":
                result = process_scheduling()
                print(f"🤖 {result}")
                speak_text(result)
            elif confirmation == "no":
                speak_text("Okay, I won’t schedule it.")
            else:
                speak_text("Sorry, I couldn't understand your confirmation. Please try again.")
        else:
            print("Say 'voice' or 'exit'.")


if __name__ == "__main__":
    main()
