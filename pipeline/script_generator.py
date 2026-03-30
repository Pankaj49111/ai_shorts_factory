import os
from dotenv import load_dotenv
from google import genai

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


def generate_script(topic):

    if not GEMINI_API_KEY:
        return f"""HOOK:
Did you know {topic} can completely change how you see the world?

BODY:
Here is a fascinating truth about {topic}. Scientists have discovered it works in ways most people never expect. The details are surprising and the implications are even bigger.

OUTRO:
This is just the beginning. Follow for more mind-blowing facts every day."""

    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = f"""
Write a HIGH-RETENTION YouTube Shorts script for a voiceover.

Topic: {topic}

Target length: 55 to 80 words (this will produce 20-30 seconds of audio at TTS speed).
Count your words carefully. Do NOT go below 55 or above 80 words.

Rules:
- Strong hook in first line - make the viewer stop scrolling
- Short punchy sentences (max 12 words each)
- Build curiosity through the body
- No filler, no fluff
- End with a follow/like CTA (1 sentence)

Format (use these exact labels):
HOOK:
BODY:
OUTRO:
"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )
    return response.text.strip()