import os
import asyncio
import json
import datetime
import pytz
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from elevenlabs.client import ElevenLabs
from deepgram import DeepgramClient
import google.generativeai as genai
import uuid
import aiohttp

# Configuration
SCOPES = ['https://www.googleapis.com/auth/calendar']
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
ELEVENLABS_API_KEY = os.getenv('ELEVENLABS_API_KEY')
DEEPGRAM_API_KEY = os.getenv('DEEPGRAM_API_KEY')
TIMEZONE = pytz.timezone('America/New_York')

# Initialize clients
genai.configure(api_key="AIzaSyCpV5FLWWayhB8qtAsRLrZJZvWt3Aiccgk")
deepgram = DeepgramClient(DEEPGRAM_API_KEY)
elevenlabs = ElevenLabs(api_key=ELEVENLABS_API_KEY)

class SmartScheduler:
    def __init__(self):
        self.service = self._init_calendar_service()
        self.conversation_context = {}
        self.session_id = str(uuid.uuid4())
        self.model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            tools=[
                {
                    "function_declarations": [
                        {
                            "name": "check_calendar",
                            "description": "Check Google Calendar for available slots",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "start_time": {"type": "string", "format": "date-time"},
                                    "end_time": {"type": "string", "format": "date-time"},
                                    "duration": {"type": "integer"}
                                },
                                "required": ["start_time", "end_time", "duration"]
                            }
                        }
                    ]
                }
            ]
        )

    def _init_calendar_service(self):
        creds = None
        if os.path.exists('token.json'):
            creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
            with open('token.json', 'w') as token:
                token.write(creds.to_json())
        return build('calendar', 'v3', credentials=creds)

    async def process_audio_input(self, audio_path):
        try:
            with open(audio_path, 'rb') as audio_file:
                response = await deepgram.listen.asyncrest.v("1").transcribe_file(
                    audio_file, {"model": "nova-2", "language": "en-US"}
                )
            return response["results"]["channels"][0]["alternatives"][0]["transcript"]
        except FileNotFoundError:
            print(f"Audio file {audio_path} not found. Using text input instead.")
            return input("Enter your scheduling request (or 'exit' to quit): ")

    async def generate_voice_response(self, text):
        print(f"Assistant: {text}")  # Log response for testing
        try:
            # Use the text-to-speech API from ElevenLabs
            async with aiohttp.ClientSession() as session:
                # Generate audio using the ElevenLabs client
                audio_stream = await self.elevenlabs.text_to_speech.convert(
                    voice_id="Rachel",  # Specify the voice ID (replace with actual voice ID if needed)
                    text=text,
                    model_id="eleven_multilingual_v2",  # Specify the model
                    stream=True  # Enable streaming
                )
                # Simulate streaming audio playback
                async for chunk in audio_stream:
                    pass  # Replace with actual audio playback logic if needed
        except Exception as e:
            print(f"Error generating voice response: {e}")
            return text
        return text

    def check_calendar(self, start_time, end_time, duration):
        try:
            events_result = self.service.events().list(
                calendarId='primary',
                timeMin=start_time,
                timeMax=end_time,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            events = events_result.get('items', [])
            start_dt = datetime.datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            end_dt = datetime.datetime.fromisoformat(end_time.replace('Z', '+00:00'))
            slots = []
            current = start_dt
            while current + datetime.timedelta(minutes=duration) <= end_dt:
                slot_end = current + datetime.timedelta(minutes=duration)
                is_free = True
                for event in events:
                    event_start = datetime.datetime.fromisoformat(event['start']['dateTime'].replace('Z', '+00:00'))
                    event_end = datetime.datetime.fromisoformat(event['end']['dateTime'].replace('Z', '+00:00'))
                    if not (slot_end <= event_start or current >= event_end):
                        is_free = False
                        break
                if is_free:
                    slots.append(current.isoformat())
                current += datetime.timedelta(minutes=30)
            return {"available_slots": slots}
        except HttpError as e:
            return {"error": str(e)}

    async def handle_conversation(self, user_input):
        self.conversation_context['last_input'] = user_input
        chat = self.model.start_chat(history=[
            {
                "role": "user",
                "parts": [{"text": json.dumps(self.conversation_context)}]
            }
        ])
        prompt = f"""
        You are a smart scheduling assistant with voice capabilities via ElevenLabs. Engage in a natural conversation to:
        1. Parse complex/vague time requests (e.g., 'next week evening', 'before my flight').
        2. Use the check_calendar tool to find available slots.
        3. Ask clarifying questions if needed (e.g., duration, preferred time).
        4. Handle conflicts gracefully (e.g., suggest alternatives if no slots).
        5. Confirm the final slot with the user.
        Current input: {user_input}
        Context: {json.dumps(self.conversation_context)}
        Respond concisely and naturally, as if speaking to a colleague.
        """
        response = await chat.send_message_async(prompt)
        
        for part in response.parts:
            if hasattr(part, 'function_call') and part.function_call:
                if part.function_call.name == "check_calendar":
                    args = part.function_call.args
                    result = self.check_calendar(
                        args['start_time'],
                        args['end_time'],
                        args['duration']
                    )
                    follow_up = await chat.send_message_async([
                        {
                            "role": "function",
                            "parts": [{"text": json.dumps(result)}]
                        }
                    ])
                    return await self.generate_voice_response(follow_up.text)
        
        return await self.generate_voice_response(response.text)

async def main():
    scheduler = SmartScheduler()
    print("Start scheduling (type or provide audio; say 'exit' to quit)...")
    audio_path = "sample_input.wav"  # Optional audio file
    while True:
        user_input = await scheduler.process_audio_input(audio_path)
        if user_input.lower() == "exit":
            break
        await scheduler.handle_conversation(user_input)

if __name__ == "__main__":
    asyncio.run(main())