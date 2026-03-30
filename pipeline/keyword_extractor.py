import os
import re
from dotenv import load_dotenv
from google import genai

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


def extract_keywords(script, count=5):
    if GEMINI_API_KEY:
        return _extract_with_gemini(script, count)
    else:
        return _extract_fallback(script, count)


def _extract_with_gemini(script, count):
    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = f"""
You are helping find b-roll footage for a YouTube Shorts video.

Given this script, return exactly {count} short search queries (2-3 words each)
that would find VISUALLY RELEVANT stock footage on Pexels.

Rules:
- Each query must describe something you can actually film (no abstract concepts)
- Prefer concrete, visual subjects: objects, places, actions, nature, science
- Do NOT return words like "memory", "fleeting", "boundless" - these film badly
- Return ONLY the queries, one per line, no numbering, no explanation

Script:
{script}
"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )
    raw = response.text.strip()

    queries = []
    for line in raw.splitlines():
        line = re.sub(r"^[\d\.\-\*\s]+", "", line).strip()
        if line:
            queries.append(line)

    queries = queries[:count]
    print(f"  Pexels queries: {queries}")
    return queries


def _extract_fallback(script, count):
    STOPWORDS = {
        "this", "that", "with", "from", "they", "them", "their",
        "have", "been", "will", "would", "could", "should", "about",
        "every", "each", "some", "like", "more", "your", "follow",
        "means", "actually", "slightly", "briefly", "almost", "better",
        "critical", "different", "anything", "wonder", "events",
        "short", "long", "term", "type", "types", "items", "hold",
    }

    words = re.findall(r'\b[a-zA-Z]{4,}\b', script.lower())
    seen = set()
    keywords = []
    for w in words:
        if w not in STOPWORDS and w not in seen:
            seen.add(w)
            keywords.append(w)
        if len(keywords) == count:
            break

    print(f"  Pexels queries (fallback): {keywords}")
    return keywords