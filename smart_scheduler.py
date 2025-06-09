# Import needed libraries
import os
import datetime
import pytz  # For handling time zones
import json  # For parsing JSON responses
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import google.generativeai as genai
from dotenv import load_dotenv

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
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
CLIENT_SECRETS_FILE = "credentials.json"
creds = None

# Check if we have a saved token
if os.path.exists("token.json"):
    try:
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    except Exception:
        print("Error: Problem with token.json file. Try deleting it and re-authenticating.")

# If no valid credentials, ask user to log in
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

# Connect to Google Calendar
try:
    calendar_service = build("calendar", "v3", credentials=creds)
except Exception:
    print("Error: Could not connect to Google Calendar.")
    exit()

# Store conversation details
conversation = {
    "duration": None,  # How long the meeting is (in minutes)
    "day": None,       # Which day (e.g., "Tuesday")
    "time": None       # Preferred time (e.g., "afternoon")
}

# Function to check available time slots in Google Calendar
def check_calendar(start_time, end_time, duration):
    try:
        # Ensure times are in UTC and ISO format
        start_time = start_time.astimezone(pytz.UTC)
        end_time = end_time.astimezone(pytz.UTC)
        
        # Get events from Google Calendar
        events_result = calendar_service.events().list(
            calendarId="primary",
            timeMin=start_time.isoformat(),
            timeMax=end_time.isoformat(),
            singleEvents=True,
            orderBy="startTime"
        ).execute()
        events = events_result.get("items", [])

        # Find free time slots
        free_slots = []
        current_time = start_time
        while current_time + datetime.timedelta(minutes=duration) <= end_time:
            slot_end = current_time + datetime.timedelta(minutes=duration)
            is_free = True
            for event in events:
                event_start = datetime.datetime.fromisoformat(event["start"]["dateTime"].replace("Z", "")).replace(tzinfo=pytz.UTC)
                event_end = datetime.datetime.fromisoformat(event["end"]["dateTime"].replace("Z", "")).replace(tzinfo=pytz.UTC)
                if not (slot_end <= event_start or current_time >= event_end):
                    is_free = False
                    break
            if is_free:
                free_slots.append(current_time)
            current_time += datetime.timedelta(minutes=30)
        return free_slots
    except HttpError as error:
        print(f"Error: Could not check Google Calendar: {error}")
        return []
    except Exception as e:
        print(f"Error: Unexpected issue checking calendar: {e}")
        return []

# Function to understand what the user said
def understand_input(user_input):
    prompt = f"""
    You are a scheduling helper. From this input, find:
    - Meeting duration (e.g., '1 hour' = 60 minutes)
    - Preferred day (e.g., 'Tuesday' or 'June 20th')
    - Preferred time (e.g., 'afternoon' or '2 PM')
    If something is missing, use null.
    Input: "{user_input}"
    Return JSON like this:
    ```json
    {{
        "meeting_duration": <number or null>,
        "preferred_day": <text or null>,
        "preferred_time": <text or null>
    }}
    ```
    """
    try:
        response = chat.send_message(prompt)
        # Parse JSON response safely
        return json.loads(response.text.strip("```json\n").strip("\n```"))
    except Exception as e:
        print(f"Error: Could not understand your input: {e}")
        return {"meeting_duration": None, "preferred_day": None, "preferred_time": None}

# Function to reply to the user
def make_reply(user_input, free_slots=None):
    current_state = f"Duration: {conversation['duration']}, Day: {conversation['day']}, Time: {conversation['time']}"
    slots_info = f"Free slots: {free_slots}" if free_slots else "No slots checked yet."
    prompt = f"""
    You are a friendly scheduling bot. Reply to the user based on their input and current state.
    - If missing info (like duration or day), ask for it.
    - If you have slots, suggest the first two.
    - If no slots, suggest another day (e.g., next day).
    - Keep replies short and friendly.
    User input: "{user_input}"
    State: {current_state}
    Slots: {slots_info}
    """
    try:
        response = chat.send_message(prompt)
        return response.text
    except Exception:
        return "Sorry, something went wrong. Please try again."

# Function to figure out which day the user means
def get_day(day_str):
    today = datetime.datetime.now(pytz.UTC)
    day_map = {
        "monday": 0, "tuesday": 1, "wednesday": 2,
        "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6
    }
    day_str = day_str.lower()

    # Handle "next week"
    if "next week" in day_str:
        today += datetime.timedelta(days=7)
    
    # Check for weekday names
    for day, offset in day_map.items():
        if day in day_str:
            days_ahead = (offset - today.weekday() + 7) % 7
            return today + datetime.timedelta(days=days_ahead)
    
    # Try to parse specific dates like "June 20th"
    try:
        return datetime.datetime.strptime(day_str, "%B %d").replace(year=today.year, tzinfo=pytz.UTC)
    except:
        return None

# Main program
def main():
    print("Smart Scheduler: Hello! Let's schedule a meeting.")
    while True:
        user_input = input("You: ")
        if user_input.lower() in ["exit", "quit"]:
            print("Smart Scheduler: Bye!")
            break

        # Understand what the user said
        info = understand_input(user_input)
        if info["meeting_duration"]:
            conversation["duration"] = info["meeting_duration"]
        if info["preferred_day"]:
            conversation["day"] = info["preferred_day"]
        if info["preferred_time"]:
            conversation["time"] = info["preferred_time"]

        # If we have enough info, check the calendar
        if conversation["duration"] and conversation["day"]:
            target_day = get_day(conversation["day"])
            if target_day:
                # Set time range (9 AM to 5 PM by default)
                start_time = target_day.replace(hour=9, minute=0, second=0, microsecond=0, tzinfo=pytz.UTC)
                end_time = target_day.replace(hour=17, minute=0, second=0, microsecond=0, tzinfo=pytz.UTC)
                
                # Adjust time based on preference
                if conversation["time"]:
                    if "afternoon" in conversation["time"].lower():
                        start_time = target_day.replace(hour=12, minute=0, tzinfo=pytz.UTC)
                    elif "morning" in conversation["time"].lower():
                        start_time = target_day.replace(hour=9, minute=0, tzinfo=pytz.UTC)
                    elif "evening" in conversation["time"].lower():
                        start_time = target_day.replace(hour=17, minute=0, tzinfo=pytz.UTC)
                
                # Check for free slots
                free_slots = check_calendar(start_time, end_time, conversation["duration"])
                if free_slots:
                    reply = make_reply(user_input, [slot.strftime("%I:%M %p") for slot in free_slots[:2]])
                else:
                    next_day = target_day + datetime.timedelta(days=1)
                    reply = make_reply(user_input, [f"No slots on {conversation['day']}. Try {next_day.strftime('%A')}?"])
            else:
                reply = make_reply(user_input, ["Please specify a valid day (e.g., 'Tuesday' or 'June 20th')."])
        else:
            reply = make_reply(user_input)

        print(f"Smart Scheduler: {reply}")

# Start the program
if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Oops! Something broke: {e}")
