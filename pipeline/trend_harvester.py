import json
import logging
import os
import random
import re
import requests
from pathlib import Path
from typing import List, Set, Dict

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# =============================================================================
# Logging
# =============================================================================
# Using absolute paths from project root to handle execution from both locations
PROJECT_ROOT = Path(__file__).resolve().parent.parent

Path(PROJECT_ROOT / "assets/logs").mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [Harvester] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(PROJECT_ROOT / "assets/logs/harvester.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("harvester")

# =============================================================================
# Config Paths
# =============================================================================
SOURCES_FILE = PROJECT_ROOT / "assets/config/trend_sources.json"
CURATED_FILE = PROJECT_ROOT / "assets/config/curated_trends.json"
SEEN_FILE = PROJECT_ROOT / "assets/logs/seen_topics.txt"


def load_seen_topics() -> Set[str]:
    if not SEEN_FILE.exists():
        return set()
    return {line.strip().lower() for line in SEEN_FILE.read_text(encoding="utf-8").splitlines() if line.strip()}


def load_sources() -> dict:
    if not SOURCES_FILE.exists():
        raise FileNotFoundError(f"Missing config: {SOURCES_FILE}")
    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        return json.load(f).get("sources", {})


def load_existing_curated() -> Dict[str, List[str]]:
    if not CURATED_FILE.exists():
        return {}
    try:
        with open(CURATED_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.warning(f"Failed to load existing curated trends: {e}")
        return {}


def scrape_reddit(subreddits: List[str], limit: int = 15) -> List[str]:
    topics = []
    headers = {"User-Agent": "ai-shorts-bot/1.5"}
    
    # Shuffle and pick a subset to avoid always scraping the same subs
    random.shuffle(subreddits)
    selected_subs = subreddits[:3]

    for sub in selected_subs:
        try:
            url = f"https://www.reddit.com/r/{sub}/top.json?t=month&limit={limit}"
            resp = requests.get(url, headers=headers, timeout=10)
            if not resp.ok:
                log.warning(f"Reddit r/{sub} failed: HTTP {resp.status_code}")
                continue
            posts = resp.json().get("data", {}).get("children", [])
            for p in posts:
                title = p["data"].get("title", "")
                # Clean typical Reddit tags
                title = re.sub(r"^(TIL|ELI5|YSK|TIL that|TIL:)\s+", "", title, flags=re.IGNORECASE)
                if len(title) > 15:
                    topics.append(title)
        except Exception as e:
            log.warning(f"Reddit scrape error for r/{sub}: {e}")
            
    return topics


def scrape_rss(feeds: List[str]) -> List[str]:
    topics = []
    try:
        import feedparser
    except ImportError:
        log.warning("feedparser not installed. Skipping RSS. Run: pip install feedparser")
        return topics

    for url in feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:
                if hasattr(entry, 'title') and len(entry.title) > 15:
                    topics.append(entry.title)
        except Exception as e:
            log.warning(f"RSS scrape error for {url}: {e}")
            
    return topics


def filter_with_gemini(cluster: str, raw_data: List[str], seen_topics: Set[str], current_pool: List[str]) -> List[str]:
    if not GEMINI_API_KEY:
        log.error("GEMINI_API_KEY missing. Cannot filter topics.")
        return []

    if not raw_data:
        log.warning(f"No raw data gathered for {cluster}.")
        return []

    client = genai.Client(api_key=GEMINI_API_KEY)
    
    # Create exclusion list context
    exclude_list = list(seen_topics) + current_pool
    random.shuffle(exclude_list)
    exclude_sample = "\n".join(f"- {t}" for t in exclude_list[:150]) # limit context size
    
    raw_text = "\n".join(f"- {item}" for item in raw_data[:100]) # cap raw data to top 100

    prompt = f"""
You are a viral YouTube Shorts producer for the '{cluster}' niche. 
Your job is to act as a data filter and title generator.

I am providing you with raw, messy data scraped from Reddit and News feeds today:
RAW DATA:
{raw_text}

Your task:
1. Extract the most bizarre, surprising, and fact-based concepts from the raw data.
2. Rewrite them into punchy, highly engaging 5-12 word topic phrases suitable for a script generator hook.
3. Discard any opinions, politics, pop culture, or boring topics.
4. Output EXACTLY 30 topic ideas.

CRITICAL INSTRUCTION - DO NOT generate any topic that is conceptually identical to these already used topics:
{exclude_sample}

Output ONLY a numbered list of topics, one per line. No introduction, no markdown.
Example format:
1. why your phone tracks location even when turned off
2. the terrifying parasite that controls the minds of insects
"""

    try:
        log.info(f"Asking Gemini to filter and format {len(raw_data)} raw items for {cluster}...")
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.7,
            )
        )
        
        new_topics = []
        for line in response.text.split("\n"):
            # Remove numbering, quotes, and markdown bullets
            line = re.sub(r"^(\d+\.\s*|\-\s*)", "", line.strip())
            line = line.strip().strip('"').strip("'")
            if line and len(line) > 10:
                # Final safeguard against duplicates before returning
                if line.lower() not in seen_topics and line.lower() not in [t.lower() for t in current_pool]:
                    new_topics.append(line)
                
        log.info(f"Gemini returned {len(new_topics)} fresh, deduplicated topics.")
        return new_topics
    except Exception as e:
        log.error(f"Gemini filtering failed for {cluster}: {e}")
        return []


def harvest():
    log.info("Starting Trend Harvest...")
    
    seen_topics = load_seen_topics()
    sources = load_sources()
    curated = load_existing_curated()
    
    total_added = 0
    
    for cluster, config in sources.items():
        log.info(f"--- Harvesting for cluster: {cluster} ---")
        
        raw_data = []
        
        # 1. Scrape Reddit
        subs = config.get("subreddits", [])
        if subs:
            log.info(f"Scraping Reddit ({len(subs)} subs)...")
            raw_data.extend(scrape_reddit(subs))
            
        # 2. Scrape RSS
        feeds = config.get("rss_feeds", [])
        if feeds:
            log.info(f"Scraping RSS ({len(feeds)} feeds)...")
            raw_data.extend(scrape_rss(feeds))
            
        log.info(f"Gathered {len(raw_data)} raw items.")
        
        # 3. Filter and Format via Gemini
        current_pool = curated.get(cluster, [])
        fresh_topics = filter_with_gemini(cluster, raw_data, seen_topics, current_pool)
        
        if fresh_topics:
            # 4. Append to pool
            if cluster not in curated:
                curated[cluster] = []
            curated[cluster].extend(fresh_topics)
            total_added += len(fresh_topics)
            
            # Keep pool manageable, retain only newest 200
            curated[cluster] = curated[cluster][-200:]
            
    # Save the updated curated pool
    if total_added > 0:
        CURATED_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CURATED_FILE, "w", encoding="utf-8") as f:
            json.dump(curated, f, indent=4)
        log.info(f"Harvest complete. Added {total_added} new topics to {CURATED_FILE.name}.")
    else:
        log.warning("Harvest complete, but no new topics were generated.")

if __name__ == "__main__":
    harvest()