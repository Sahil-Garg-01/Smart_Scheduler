# Smart Scheduler AI Agent

This project is a conversational chatbot that helps users schedule meetings by integrating with the Google Calendar API and using the Gemini API for natural language understanding. It was developed as a take-home assignment for the AI Agent Development internship at NextDimension.

## Setup Instructions

Follow these steps to set up and run the Smart Scheduler on your computer. These are designed to be simple for beginners.

### 1. Install Python
- Download and install Python 3.8 or later from [python.org](https://www.python.org/downloads/).
- Verify installation by opening a terminal (Command Prompt on Windows, Terminal on macOS/Linux) and running:
  ```bash
  python --version


Ensure pip (Python’s package manager) is installed:pip --version



2. Install Required Libraries

In your terminal, navigate to the project folder (where smart_scheduler.py is located) using:cd path/to/your/project/folder


Install the necessary Python libraries with this command:pip install google-auth==2.23.0 google-auth-oauthlib==1.0.0 google-api-python-client==2.93.0 python-dotenv==1.0.0 google-generativeai==0.8.3



3. Set Up Google Calendar API

Go to Google Cloud Console.
Create a new project (e.g., "SmartScheduler") or select an existing one.
Enable the Google Calendar API:
Navigate to APIs & Services > Library.
Search for "Google Calendar API" and click Enable.


Create OAuth 2.0 credentials:
Go to APIs & Services > Credentials.
Click + Create Credentials > OAuth client ID.
Select Desktop app as the application type, name it (e.g., "Smart Scheduler Desktop"), and click Create.
Download the JSON file (it will be named something like client_secret_*.json).
Rename it to credentials.json and place it in the same folder as smart_scheduler.py.


Configure the OAuth consent screen:
Go to APIs & Services > OAuth consent screen.
Select External and click Create.
Fill in required fields (e.g., App name: "Smart Scheduler", User support email: your email).
Skip adding scopes (use default) and save.
Under Test users, add your Google account email (the one you’ll use to test) and save.



4. Set Up Gemini API Key

Go to Google AI Studio.
Sign in and generate an API key.
Create a file named .env in the same folder as smart_scheduler.py.
Add your API key to the .env file like this:GOOGLE_API_KEY=your_gemini_api_key_here



5. Run the Project

In the terminal, ensure you’re in the project folder and run:python smart_scheduler.py


The first time you run it, a browser will open asking you to log in to your Google account (use the test user account added above).
Approve the permissions to access your calendar (read-only).
The script will create a token.json file for future authentication.
Interact with the chatbot by typing inputs like:
"I need a 1-hour meeting."
"Tuesday afternoon."
Type exit or quit to stop.



Troubleshooting

Missing credentials.json: Ensure it’s downloaded from Google Cloud Console and placed in the project folder.
Authentication errors: Delete token.json and rerun the script to re-authenticate.
API key errors: Verify your Gemini API key in the .env file.
No slots found: Add some events to your Google Calendar for testing, or ensure the calendar is accessible.

Design Choices and How It Works
Overview
The Smart Scheduler is a Python-based chatbot that helps users find available meeting times by talking to them naturally. It uses the Gemini API to understand user inputs and the Google Calendar API to check for free time slots. The design prioritizes simplicity, reliability, and a beginner-friendly codebase while meeting the assignment’s requirements.
Key Design Choices

Python for Simplicity:

Chose Python for its readability and ease of use, ideal for rapid development and debugging.
Avoided complex frameworks or no/low-code tools (like n8n) to keep full control over the logic.


Gemini API for Natural Language:

Used Google’s Gemini 1.5 Flash model for its ability to parse user inputs (e.g., "1 hour" or "Tuesday afternoon") and generate friendly responses.
Designed prompts to extract structured data (duration, day, time) and handle conversational flow.


Google Calendar API Integration:

Connected to the user’s primary calendar with read-only access to check availability.
Implemented a slot-finding algorithm that looks for free time windows based on the meeting duration.


State Management:

Stored conversation details (duration, day, time) in a simple dictionary to track user preferences across multiple turns.
Ensured the bot remembers context (e.g., meeting duration) to avoid repetitive questions.


Error Handling:

Added clear error messages for common issues (e.g., missing files, API errors) to make debugging easy.
Used try-except blocks to prevent crashes and guide users to fixes.


Conflict Resolution:

If no slots are available, the bot suggests the next day (e.g., "No slots on Tuesday. Try Wednesday?") to handle conflicts gracefully.
Kept this simple to meet the assignment’s bonus point for conflict resolution without overcomplicating.



How the Agent Works

User Interaction:

The user starts by typing something like "I need a 1-hour meeting."
The bot runs in a loop, accepting inputs until the user types exit or quit.


Input Parsing:

The Gemini API analyzes the input to extract:
Meeting duration (e.g., "1 hour" → 60 minutes).
Preferred day (e.g., "Tuesday" or "June 20th").
Preferred time (e.g., "afternoon").


If info is missing, the bot asks clarifying questions (e.g., "What day and time works best?").


Calendar Check:

When enough info is provided (duration and day), the bot calculates the target day (e.g., next Tuesday).
It sets a time range (e.g., 12 PM–5 PM for "afternoon") and checks the Google Calendar for free slots.
The bot looks for gaps where no events overlap with the requested duration.


Response Generation:

If slots are found, the bot suggests up to two (e.g., "I have 2:00 PM or 4:30 PM available. Which works?").
If no slots, it suggests the next day.
The Gemini API generates friendly, natural responses based on the conversation state.



Example Conversation
Smart Scheduler: Hello! Let's schedule a meeting.
You: I need a 1-hour meeting.
Smart Scheduler: Okay, a 1-hour meeting. What day and time works best for you?
You: Tuesday afternoon.
Smart Scheduler: I have 2:00 PM or 4:30 PM available on Tuesday. Which one works?

Or, if no slots:
Smart Scheduler: No slots on Tuesday. Try Wednesday?

Why It Meets the Assignment

Agentic Logic: Maintains conversation context and decides when to ask questions or check the calendar.
Prompt Engineering: Uses clear prompts to guide Gemini for input parsing and response generation.
API Integration: Correctly authenticates and uses the Google Calendar API to find free slots.
Problem-Solving: Handles edge cases like missing info or no available slots with simple conflict resolution.

This project is a solid foundation for a scheduling agent, with room to add features like voice input or advanced time parsing if needed.```
