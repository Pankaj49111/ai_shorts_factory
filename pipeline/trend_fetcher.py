import os
import re
import random
import time
import requests
from datetime import date
from dotenv import load_dotenv
from google import genai
from typing import Set, List

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# --- Niche Profiles for Daily Rotation ---
NICHE_PROFILES = [
    # Profile 1: Core Science & Space
    "A YouTube Shorts channel posting mind-blowing science, space, and nature facts. Topics must be visually stunning and scientifically shocking.",
    
    # Profile 2: Psychology & Human Behavior
    "A YouTube Shorts channel posting dark psychology, human behavior, and body language facts. Topics must make the viewer rethink how they interact with the world.",
    
    # Profile 3: History & Lost Civilizations
    "A YouTube Shorts channel posting bizarre history, lost civilizations, and ancient mysteries. Avoid boring dates; focus on shocking historical events or practices.",
    
    # Profile 4: Futurology & Deep Tech
    "A YouTube Shorts channel posting about crazy future technology, AI, robotics, and cybernetics. Focus on things that sound like sci-fi but are actually real.",
    
    # Profile 5: Finance & Wealth Psychology
    "A YouTube Shorts channel posting about the psychology of money, extreme wealth facts, and bizarre economic events. Keep it focused on facts, not financial advice.",
    
    # Profile 6: Nature & Bizarre Biology
    "A YouTube Shorts channel posting about terrifying animals, weird ecosystems, and biological marvels. Focus on the most extreme aspects of nature.",
    
    # Profile 7: Myths, Legends & Folklore
    "A YouTube Shorts channel exploring the shocking real-life origins of myths, legends, and urban legends. Focus on the facts behind the fiction."
]

def _get_daily_niche() -> str:
    """Selects a niche profile based on the current day of the year."""
    # Use the day of the year to ensure the same niche is picked all day,
    # but it changes every single day.
    day_of_year = date.today().toordinal()
    niche_index = day_of_year % len(NICHE_PROFILES)
    return NICHE_PROFILES[niche_index]


# --- How many trending topics to collect before filtering ---
TOPICS_TO_COLLECT = 25


# ---------------------------------------------------------------------------
# Source 1: Google Trends via pytrends
# ---------------------------------------------------------------------------

def _fetch_google_trends():
    try:
        from pytrends.request import TrendReq
        pt = TrendReq(hl="en-US", tz=360)
        df = pt.trending_searches(pn="united_states")
        if df is not None and not df.empty and len(df) > 0:
            topics = df[0].tolist()[:10]
            print(f"  Google Trends: {len(topics)} topics")
            return topics
        else:
            print("  Google Trends: No data returned")
            return []
    except Exception as e:
        error_msg = str(e).lower()
        if "404" in error_msg:
            print("  Google Trends failed: Google blocked the request (404) - this is common")
        elif "429" in error_msg or "rate limit" in error_msg:
            print("  Google Trends failed: Rate limited - try again later")
        else:
            print(f"  Google Trends failed: {e}")
        return []


# ---------------------------------------------------------------------------
# Source 2: Reddit — Targeted subreddits for science/facts
# ---------------------------------------------------------------------------

def _fetch_reddit():
    topics  = []
    headers = {"User-Agent": "ai-shorts-bot/1.3"}
    # Added highly viral, fact-based subreddits
    subs    = [
        "todayilearned", "science", "interestingasfuck", "mindblowing",
        "Damnthatsinteresting", "space", "psychology", "explainlikeimfive",
        "Showerthoughts", "YouShouldKnow", "Awwducational", "CreepyWikipedia",
        "coolguides", "natureismetal"
    ]
    
    # Shuffle and pick 5 random subreddits per run to ensure constant variety
    random.shuffle(subs)
    selected_subs = subs[:5]

    for sub in selected_subs:
        try:
            # Using 't=week' instead of 'day' gets much higher quality, proven viral posts
            url  = f"https://www.reddit.com/r/{sub}/top.json?t=week&limit=5"
            resp = requests.get(url, headers=headers, timeout=10)
            if not resp.ok:
                print(f"  Reddit r/{sub} failed: HTTP {resp.status_code}")
                continue
            posts = resp.json()["data"]["children"]
            for p in posts:
                title = p["data"]["title"]
                title = re.sub(r"^(TIL|ELI5|YSK|TIL that|TIL:)\s+", "", title, flags=re.IGNORECASE)
                topics.append(title)
        except Exception as e:
            print(f"  Reddit r/{sub} failed: {e}")

    print(f"  Reddit: {len(topics)} topics from {', '.join(selected_subs)}")
    return topics


# ---------------------------------------------------------------------------
# Source 3: Wikipedia trending pages (most viewed today)
# ---------------------------------------------------------------------------

def _fetch_wikipedia_trending():
    try:
        # FIX: Wikipedia pageviews API takes ~12-24 hours to update.
        # If run early in the day, yesterday's data 404s. Using "2 days ago" is much safer.
        target_date = date.fromordinal(date.today().toordinal() - 2)
        url = (
            f"https://wikimedia.org/api/rest_v1/metrics/pageviews/top/"
            f"en.wikipedia/all-access/{target_date.year}/"
            f"{target_date.month:02d}/{target_date.day:02d}"
        )
        headers = {"User-Agent": "ai-shorts-bot/1.3 (bot@example.com)"}
        resp   = requests.get(url, headers=headers, timeout=10)
        
        if not resp.ok:
            print(f"  Wikipedia trending failed: HTTP {resp.status_code} - {resp.text[:50]}")
            return []
            
        data = resp.json()
        if "items" not in data or not data["items"]:
            print("  Wikipedia trending failed: No items found in response")
            return []
            
        items  = data["items"][0]["articles"]
        topics = [
            i["article"].replace("_", " ")
            for i in items[:25]
            if not any(i["article"].startswith(p) for p in
                       ["Main_Page", "Special:", "Wikipedia:", "Portal:", "Help:"])
        ][:10]
        print(f"  Wikipedia: {len(topics)} topics")
        return topics
    except Exception as e:
        print(f"  Wikipedia trending failed Exception: {e}")
        return []

# ---------------------------------------------------------------------------
# Source 4: Hacker News - Top stories filtered for science/tech
# ---------------------------------------------------------------------------

def _fetch_hacker_news():
    topics = []
    try:
        base_url = "https://hacker-news.firebaseio.com/v0"
        top_stories_url = f"{base_url}/topstories.json"
        
        resp = requests.get(top_stories_url, timeout=10)
        if not resp.ok:
            print(f"  Hacker News failed: Could not fetch top stories (HTTP {resp.status_code})")
            return []

        story_ids = resp.json()[:25]
        
        for story_id in story_ids:
            story_url = f"{base_url}/item/{story_id}.json"
            story_resp = requests.get(story_url, timeout=5)
            if story_resp.ok:
                story_data = story_resp.json()
                title = story_data.get("title", "")
                if any(keyword in title.lower() for keyword in ["science", "psychology", "brain", "study", "discover", "nasa", "space", "research", "physics"]):
                    topics.append(title)
        
        print(f"  Hacker News: {len(topics)} relevant topics found")
        return topics[:5]

    except Exception as e:
        print(f"  Hacker News failed: {e}")
        return []

# ---------------------------------------------------------------------------
# Source 5: Google News trending topics
# ---------------------------------------------------------------------------

def _fetch_google_news_trending():
    try:
        url = "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=10)
        if not resp.ok:
            print(f"  Google News failed: HTTP {resp.status_code}")
            return []

        import xml.etree.ElementTree as ET
        root = ET.fromstring(resp.content)
        topics = []
        for item in root.findall('.//item')[:20]:
            title_elem = item.find('title')
            if title_elem is not None:
                topics.append(title_elem.text)
        
        print(f"  Google News: {len(topics)} topics")
        return topics[:10]

    except Exception as e:
        print(f"  Google News trending failed: {e}")
        return []

# ---------------------------------------------------------------------------
# Source 6: Random Facts API (Evergreen fallback)
# ---------------------------------------------------------------------------

def _fetch_random_facts():
    """Fetches random obscure facts from a public API, great for endless evergreen content."""
    topics = []
    try:
        url = "https://uselessfacts.jsph.pl/api/v2/facts/random"
        for _ in range(3):
            resp = requests.get(url, timeout=5)
            if resp.ok:
                fact = resp.json().get("text")
                if fact:
                    # Keep it short for the topic selection
                    topics.append(fact[:100] + "...")
            time.sleep(0.5)
        print(f"  Random Facts API: {len(topics)} topics")
        return topics
    except Exception as e:
        print(f"  Random Facts API failed: {e}")
        return []

# ---------------------------------------------------------------------------
# Gemini niche filter — picks the best topic for your channel
# ---------------------------------------------------------------------------

def _filter_with_gemini(topics: List[str], exclude_topics: Set[str]) -> str:
    # Get the specific niche profile for today
    current_niche = _get_daily_niche()
    print(f"  Using Daily Niche Profile: {current_niche[:50]}...")

    if not GEMINI_API_KEY:
        print("  No Gemini key — returning first topic as fallback")
        return topics[0] if topics else "optical illusions brain"

    client = genai.Client(api_key=GEMINI_API_KEY)

    topics_list = "\n".join(f"{i+1}. {t}" for i, t in enumerate(topics))
    exclude_list = "\n".join(f"- {t}" for t in exclude_topics)

    prompt = f"""
You are selecting the best topic for a YouTube Shorts video.

Channel niche for today:
{current_niche}

Trending topics collected today:
{topics_list}

Topics to AVOID (already used recently):
{exclude_list}

Your job:
1. Score each topic 1-10 for how well it fits the channel niche.
2. Favour topics that are: surprising, visual, explainable in 30 seconds, curiosity-triggering.
3. Avoid: politics, celebrities, sports, disasters, deaths, breaking news, AND any topics from the "Topics to AVOID" list.
4. Return ONLY the single best topic as a short 2-5 word phrase suitable for a script prompt.
5. If NONE of the topics fit well, INVENT a highly viral evergreen topic that perfectly matches the "Channel niche for today" (e.g. "terrifying space facts" or "glitches in human perception").
6. No explanation, no numbering, just the topic phrase.

Example good output: "why humans forget dreams"
Example bad output: "1. brain memory (score: 8) - this fits because..."
"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )

    topic = response.text.strip().strip('"').strip("'")
    print(f"  Gemini selected: '{topic}'")
    return topic


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def get_trending_topic(exclude_topics: Set[str]) -> str:
    """
    Fetch trending topics from all sources, filter for niche fit and against seen topics,
    return the single best fresh topic string for script generation.
    """
    print("Fetching trending topics...")

    all_topics = []
    all_topics.extend(_fetch_google_trends())
    time.sleep(1)
    all_topics.extend(_fetch_reddit())
    time.sleep(1)
    all_topics.extend(_fetch_wikipedia_trending())
    time.sleep(1)
    all_topics.extend(_fetch_hacker_news())
    time.sleep(1)
    all_topics.extend(_fetch_google_news_trending())
    time.sleep(1)
    all_topics.extend(_fetch_random_facts())

    # Deduplicate and filter out topics already seen
    unique_fresh_topics = []
    seen_so_far = set()
    for t in all_topics:
        key = t.lower().strip()
        if key and key not in seen_so_far and key not in exclude_topics:
            seen_so_far.add(key)
            unique_fresh_topics.append(t)

    print(f"  Total unique fresh topics collected: {len(unique_fresh_topics)}")

    if not unique_fresh_topics:
        print("  All sources failed or all topics seen — using fallback topic")
        return "surprising human brain facts"

    candidates = unique_fresh_topics[:TOPICS_TO_COLLECT]

    return _filter_with_gemini(candidates, exclude_topics)