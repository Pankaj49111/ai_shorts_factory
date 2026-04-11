import os
import re
from dotenv import load_dotenv
from pipeline.llm_manager import generate_completion

load_dotenv()

def extract_pexels_queries(script, count=5):
    try:
        return _extract_pexels_with_llm(script, count)
    except Exception as e:
        print(f"LLM extraction failed: {e}")
        return _extract_pexels_fallback(script, count)

def _extract_pexels_with_llm(script, count):
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

    raw = generate_completion(prompt, task_type="utility", temperature=0.5, max_tokens=100)

    queries = []
    for line in raw.splitlines():
        line = re.sub(r"^[\d\.\-\*\s]+", "", line).strip()
        if line:
            queries.append(line)

    queries = queries[:count]
    print(f"  Pexels queries: {queries}")
    return queries

def _extract_pexels_fallback(script, count):
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

def extract_youtube_tags(script, count=10):
    try:
        return _extract_youtube_tags_with_llm(script, count)
    except Exception as e:
        print(f"LLM tag extraction failed: {e}")
        return _extract_youtube_tags_fallback(script, count)

def _extract_youtube_tags_with_llm(script, count):
    prompt = f"""
You are an expert YouTube SEO specialist.

Given the following video script, generate exactly {count} highly relevant and concise
YouTube tags.

Rules:
- Each tag should be a single word or a short phrase (max 3 words).
- Tags should be directly related to the content of the script.
- Avoid generic tags like "video", "short", "youtube".
- Avoid special characters.
- Return ONLY the tags, one per line, no numbering, no explanation.

Script:
{script}
"""
    raw = generate_completion(prompt, task_type="utility", temperature=0.5, max_tokens=150)

    tags = []
    for line in raw.splitlines():
        line = re.sub(r"^[\d\.\-\*\s]+", "", line).strip()
        if line:
            tags.append(line)

    tags = tags[:count]
    print(f"  YouTube tags: {tags}")
    return tags

def _extract_youtube_tags_fallback(script, count):
    STOPWORDS = {
        "this", "that", "with", "from", "they", "them", "their",
        "have", "been", "will", "would", "could", "should", "about",
        "every", "each", "some", "like", "more", "your", "follow",
        "means", "actually", "slightly", "briefly", "almost", "better",
        "critical", "different", "anything", "wonder", "events",
        "short", "long", "term", "type", "types", "items", "hold",
        "youtube", "video", "shorts", "short", "fact", "facts", "daily"
    }

    words = re.findall(r'\b[a-zA-Z]{2,}\b', script.lower())
    seen = set()
    tags = []
    for w in words:
        if w not in STOPWORDS and w not in seen:
            seen.add(w)
            tags.append(w)
        if len(tags) == count:
            break
    print(f"  YouTube tags (fallback): {tags}")
    return tags