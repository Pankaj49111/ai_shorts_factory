import sys
from pathlib import Path

# Ensure the root project directory is in the sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import json
import logging
import os
import random
import re
import requests
from typing import List, Set, Dict

from dotenv import load_dotenv
from pipeline.llm_manager import generate_completion
from googleapiclient.discovery import build

load_dotenv()

# =============================================================================
# Logging
# =============================================================================
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

# YouTube API client initialization
_yt_client = None

def get_yt_client():
    global _yt_client
    if _yt_client is None:
        try:
            from google.oauth2.credentials import Credentials
            token_path = PROJECT_ROOT / "credentials" / "token.json"
            if not token_path.exists():
                log.warning("YouTube token.json not found. YouTube scraping will be skipped.")
                return None
                
            creds = Credentials.from_authorized_user_file(str(token_path), ["https://www.googleapis.com/auth/youtube.readonly"])
            _yt_client = build("youtube", "v3", credentials=creds)
        except Exception as e:
            log.warning(f"Failed to initialize YouTube client: {e}")
            return None
    return _yt_client


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


def scrape_youtube(channels: List[str], max_videos_per_channel: int = 5) -> List[str]:
    """
    Scrapes the latest video titles from a list of YouTube channel handles.
    Uses the authenticated OAuth token via the YouTube Data API v3.
    Cost: ~101 quota units per channel (100 for search, 1 for playlistItems).
    """
    topics = []
    yt = get_yt_client()
    if not yt:
        return topics
        
    random.shuffle(channels)
    # Pick a subset to keep quota absolutely minimal and vary sources
    selected_channels = channels[:3]

    for handle in selected_channels:
        try:
            # 1. Resolve handle/username to Channel ID and get their Uploads playlist ID
            # First, check if it's already an ID vs a handle/username
            if handle.startswith("UC") and len(handle) == 24:
                channel_response = yt.channels().list(
                    part="contentDetails",
                    id=handle
                ).execute()
            else:
                # Handle @username format or plain username
                search_q = handle if handle.startswith("@") else f"@{handle}"
                search_response = yt.search().list(
                    part="snippet",
                    q=search_q,
                    type="channel",
                    maxResults=1
                ).execute()
                
                if not search_response.get("items"):
                    log.warning(f"Could not resolve YouTube channel: {handle}")
                    continue
                    
                channel_id = search_response["items"][0]["snippet"]["channelId"]
                
                channel_response = yt.channels().list(
                    part="contentDetails",
                    id=channel_id
                ).execute()

            if not channel_response.get("items"):
                continue

            # The ID of the playlist that contains the channel's uploaded videos
            uploads_playlist_id = channel_response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

            # 2. Fetch the latest videos from that playlist
            playlist_response = yt.playlistItems().list(
                part="snippet",
                playlistId=uploads_playlist_id,
                maxResults=max_videos_per_channel
            ).execute()

            for item in playlist_response.get("items", []):
                title = item["snippet"]["title"]
                if len(title) > 15:
                    # Clean out common YT title fluff
                    clean_title = re.sub(r"(?i)(#shorts|#short|#viral)", "", title).strip()
                    topics.append(clean_title)

        except Exception as e:
            log.warning(f"YouTube scrape error for {handle}: {e}")

    return topics


def filter_with_llm(cluster: str, raw_data: List[str], seen_topics: Set[str], current_pool: List[str]) -> List[str]:
    if not raw_data:
        log.warning(f"No raw data gathered for {cluster}.")
        return []

    # Create exclusion list context
    exclude_list = list(seen_topics) + current_pool
    random.shuffle(exclude_list)
    exclude_sample = "\n".join(f"- {t}" for t in exclude_list[:150]) # limit context size
    
    raw_text = "\n".join(f"- {item}" for item in raw_data[:100]) # cap raw data to top 100

    prompt = f"""
You are a viral YouTube Shorts producer for the '{cluster}' niche. 
Your job is to act as a data filter and title generator.

I am providing you with raw, messy data scraped from Reddit, RSS, and YouTube today:
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
        log.info(f"Asking LLM to filter and format {len(raw_data)} raw items for {cluster}...")
        raw = generate_completion(prompt, task_type="utility", temperature=0.7, max_tokens=1500)
        
        new_topics = []
        for line in raw.split("\n"):
            # Remove numbering, quotes, and markdown bullets
            line = re.sub(r"^(\d+\.\s*|\-\s*)", "", line.strip())
            line = line.strip().strip('"').strip("'")
            if line and len(line) > 10:
                # Final safeguard against duplicates before returning
                if line.lower() not in seen_topics and line.lower() not in [t.lower() for t in current_pool]:
                    new_topics.append(line)
                
        log.info(f"LLM returned {len(new_topics)} fresh, deduplicated topics.")
        return new_topics
    except Exception as e:
        log.error(f"LLM filtering failed for {cluster}: {e}")
        return []


def harvest():
    log.info("Starting Trend Harvest...")
    
    seen_topics = load_seen_topics()
    sources = load_sources()
    curated = load_existing_curated()
    
    total_added = 0
    
    for cluster, config in sources.items():
        log.info(f"--- Harvesting for cluster: {cluster} ---")
        
        current_pool = curated.get(cluster, [])
        if len(current_pool) > 45:
            log.info(f"Skipping cluster {cluster} — pool already has {len(current_pool)} topics (>45).")
            continue
        
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
            
        # 3. Scrape YouTube
        channels = config.get("youtube_channels", [])
        if channels:
            log.info(f"Scraping YouTube ({len(channels)} channels)...")
            yt_data = scrape_youtube(channels)
            if yt_data:
                raw_data.extend(yt_data)
            
        log.info(f"Gathered {len(raw_data)} raw items.")
        
        # 4. Filter and Format via LLM
        fresh_topics = filter_with_llm(cluster, raw_data, seen_topics, current_pool)
        
        if fresh_topics:
            # 5. Append to pool
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