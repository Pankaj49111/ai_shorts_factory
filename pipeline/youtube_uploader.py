"""
youtube_uploader.py  —  AI Shorts Factory
==========================================
OAuth upload + viral metadata generation for YouTube Shorts.

One-time local setup
---------------------
1.  Google Cloud Console → new project → Enable "YouTube Data API v3"
2.  Credentials → OAuth 2.0 Client ID → Desktop App → download JSON
    → save as  credentials/client_secret.json
3.  python pipeline/youtube_uploader.py
    Browser opens once; token saved to credentials/token.json.
    All future pipeline runs are fully silent.

.env
----
YOUTUBE_CLIENT_SECRET_PATH   default: credentials/client_secret.json
YOUTUBE_TOKEN_PATH            default: credentials/token.json
YOUTUBE_DEFAULT_PRIVACY       public | unlisted | private  (default: public)
YOUTUBE_CHANNEL_NICHE         e.g. "science facts"
"""

from __future__ import annotations

import os
import re
import sys
import time
import random
import logging
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    import google.auth.exceptions
except ImportError as exc:
    raise SystemExit(
        "pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib"
    ) from exc

log = logging.getLogger(__name__)

SCOPES          = ["https://www.googleapis.com/auth/youtube.upload"]
API_SERVICE     = "youtube"
API_VERSION     = "v3"
MAX_RETRIES     = 5
RETRIABLE_CODES = {500, 502, 503, 504}

CATEGORY = {
    "education"    : "27",
    "science_tech" : "28",
    "entertainment": "24",
    "news_politics": "25",
    "people_blogs" : "22",
}

_BASE_TAGS = ["Shorts", "YouTubeShorts", "Short", "viral", "trending"]

_NICHE_TAGS: dict[str, list[str]] = {
    "tech"    : ["technology", "tech", "AI", "gadgets", "innovation", "futuretech"],
    "science" : ["science", "space", "physics", "nature", "biology", "discovery"],
    "history" : ["history", "historyfacts", "didyouknow", "ancienthistory"],
    "finance" : ["money", "investing", "finance", "wealth", "stockmarket"],
    "health"  : ["health", "wellness", "fitness", "nutrition", "mentalhealth"],
    "facts"   : ["facts", "amazingfacts", "mindblowing", "didyouknow", "education"],
    "news"    : ["news", "worldnews", "breakingnews", "currentevents"],
}

_TITLE_EMOJIS = ["🤯", "😱", "🔥", "💡", "⚡", "🚀", "👀", "🧠", "💥", "🎯"]

_CTA_LINES = [
    "👍 Like if you learned something new!",
    "🔔 Subscribe for daily facts you won't believe.",
    "📌 Follow for more — new video every day.",
    "💬 Drop a comment — did you already know this?",
    "🔁 Share this with someone who needs to know.",
    "📲 Save this for later!",
    "🔥 Follow for more in 60 seconds.",
]

_NICHE_HASHTAGS: dict[str, str] = {
    "tech"    : "#Tech #AI #Technology #Innovation #FutureTech",
    "science" : "#Science #Space #Physics #Nature #Discovery",
    "history" : "#History #HistoryFacts #DidYouKnow #AncientHistory",
    "finance" : "#Money #Finance #Investing #WealthTips",
    "health"  : "#Health #Fitness #Wellness #MentalHealth",
    "facts"   : "#Facts #AmazingFacts #MindBlowing #Education",
    "news"    : "#News #WorldNews #BreakingNews #CurrentEvents",
}


# =============================================================================
# Pre-flight check  (called by pipeline_runner before attempting upload)
# =============================================================================

def is_youtube_configured() -> bool:
    """
    FIX: Returns True only if client_secret.json exists.
    Called once upfront by pipeline_runner so we never retry a config error.
    """
    secret_path = Path(
        os.getenv("YOUTUBE_CLIENT_SECRET_PATH", "credentials/client_secret.json")
    )
    if not secret_path.exists():
        log.warning(
            f"YouTube not configured: '{secret_path}' missing.\n"
            "  Setup steps:\n"
            "    1. Google Cloud Console → Enable YouTube Data API v3\n"
            "    2. Credentials → OAuth 2.0 Client ID → Desktop App → download JSON\n"
            f"    3. Save the file as: {secret_path}\n"
            "    4. Run once: python pipeline/youtube_uploader.py\n"
            "    5. Sign in — token.json is saved, all future runs are silent."
        )
        return False
    return True


# =============================================================================
# Auth
# =============================================================================

def _get_credentials() -> Credentials:
    secret_path = Path(os.getenv("YOUTUBE_CLIENT_SECRET_PATH", "credentials/client_secret.json"))
    token_path  = Path(os.getenv("YOUTUBE_TOKEN_PATH", "credentials/token.json"))

    if not secret_path.exists():
        raise FileNotFoundError(
            f"client_secret.json not found at '{secret_path}'.\n"
            "Run  python pipeline/youtube_uploader.py  after placing the file."
        )

    creds: Optional[Credentials] = None

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                log.info("OAuth token refreshed.")
            except google.auth.exceptions.RefreshError:
                log.warning("Token refresh failed — re-authenticating.")
                creds = None

        if not creds:
            flow  = InstalledAppFlow.from_client_secrets_file(str(secret_path), SCOPES)
            creds = flow.run_local_server(port=0)
            log.info("New OAuth token obtained.")

        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")

    return creds


def _build_service():
    return build(API_SERVICE, API_VERSION, credentials=_get_credentials())


# =============================================================================
# Upload
# =============================================================================

def _upload_with_retry(youtube, body: dict, media: MediaFileUpload) -> str:
    req     = youtube.videos().insert(part=",".join(body.keys()), body=body, media_body=media)
    resp    = None
    error   = None
    attempt = 0

    while resp is None:
        try:
            status, resp = req.next_chunk()
            if status:
                log.info(f"  Upload progress: {int(status.progress() * 100)}%")
        except HttpError as e:
            if e.resp.status in RETRIABLE_CODES:
                error = f"HTTP {e.resp.status}"
            else:
                raise
        except Exception as e:
            error = str(e)

        if error:
            attempt += 1
            if attempt > MAX_RETRIES:
                raise RuntimeError(f"Upload failed after {MAX_RETRIES} retries: {error}")
            wait = (2 ** attempt) + random.random()
            log.warning(f"Retriable error ({error}) — retry {attempt}/{MAX_RETRIES} in {wait:.1f}s")
            time.sleep(wait)
            error = None

    video_id = resp.get("id")
    if not video_id:
        raise RuntimeError(f"No video ID in response: {resp}")
    return video_id


def upload_short(
        video_path: str,
        title: str,
        description: str = "",
        tags: Optional[list[str]] = None,
        category_id: str = CATEGORY["education"],
        privacy: Optional[str] = None,
        made_for_kids: bool = False,
        notify_subscribers: bool = False,
        publish_at: Optional[str] = None, # New parameter for scheduling
) -> str:
    """
    Upload a local .mp4 as a YouTube Short. Returns the video ID.
    Can also schedule the video for a future publish time.
    """
    path    = Path(video_path)
    # If publish_at is set, privacy must be 'private' for scheduling
    effective_privacy = "private" if publish_at else (privacy or os.getenv("YOUTUBE_DEFAULT_PRIVACY", "private"))

    if not path.exists():
        raise FileNotFoundError(f"Video not found: {path}")
    if effective_privacy not in {"public", "unlisted", "private"}:
        raise ValueError(f"Invalid privacy: {effective_privacy!r}")

    all_tags = list(dict.fromkeys(_BASE_TAGS + (tags or [])))

    status_body = {
        "privacyStatus"           : effective_privacy,
        "selfDeclaredMadeForKids" : made_for_kids,
        "madeForKids"             : made_for_kids,
    }

    if publish_at:
        status_body["publishAt"] = publish_at
        log.info(f"Video scheduled for: {publish_at}")

    body = {
        "snippet": {
            "title"          : title[:100],
            "description"    : description[:5000],
            "tags"           : all_tags[:500],
            "categoryId"     : category_id,
            "defaultLanguage": "en",
        },
        "status": status_body,
    }

    media = MediaFileUpload(
        str(path), mimetype="video/mp4", resumable=True, chunksize=256 * 1024
    )

    log.info(f"Authenticating with YouTube…")
    yt = _build_service()
    log.info(f"Uploading '{title}' ({path.stat().st_size / 1_048_576:.1f} MB, privacy={effective_privacy})")
    video_id = _upload_with_retry(yt, body, media)
    log.info(f"Upload complete → https://www.youtube.com/shorts/{video_id}")
    return video_id


# =============================================================================
# Metadata builder
# =============================================================================

def _detect_niche(topic: str, script: str) -> str:
    env = os.getenv("YOUTUBE_CHANNEL_NICHE", "").lower()
    for key in _NICHE_TAGS:
        if key in env:
            return key
    text   = (topic + " " + script).lower()
    scores = {k: sum(1 for kw in v if kw.lower() in text) for k, v in _NICHE_TAGS.items()}
    best   = max(scores, key=scores.get)
    return best if scores[best] > 0 else "facts"


def _build_title(topic: str) -> str:
    base = topic.strip().rstrip("?!.")
    if not topic.strip().endswith("?"):
        templates = [
            f"Did You Know {base}?",
            f"Why {base} Will Shock You",
            f"The Truth About {base}",
            f"{base} — Most People Don't Know This",
            f"What Happens When {base}?",
            f"Nobody Talks About {base}",
        ]
        base = random.choice(templates)
    emoji = random.choice(_TITLE_EMOJIS)
    return f"{base} {emoji}"[:100]


def _build_description(topic: str, script: str, niche: str) -> str:
    cta        = random.choice(_CTA_LINES)
    niche_hash = _NICHE_HASHTAGS.get(niche, _NICHE_HASHTAGS["facts"])
    first_line = script.split(".")[0].strip()
    
    # Try to get channel name from env variable, default to empty string if not set
    channel_name = os.getenv("YOUTUBE_CHANNEL_NAME", "")
    channel_tag = f"@{channel_name}" if channel_name else ""

    return (
        f"{first_line}.\n"
        f"Watch to the end — the last fact will surprise you.\n\n"
        f"{'─' * 32}\n\n"
        f"{script.strip()}\n\n"
        f"{'─' * 32}\n\n"
        f"{cta} {channel_tag}\n\n"
        f"0:00 — {topic}\n\n"
        f"#Shorts #YouTubeShorts {niche_hash} #DidYouKnow #Facts #Viral #LearnOnShorts"
    )[:5000]


def _build_tags(topic: str, script: str, niche: str, extra: Optional[list[str]] = None) -> list[str]:
    topic_tags  = [w.strip(".,!?\"'") for w in topic.split() if len(w) > 3]
    words       = re.findall(r"\b[A-Za-z]{5,}\b", script)
    freq: dict  = {}
    for w in words:
        freq[w.lower()] = freq.get(w.lower(), 0) + 1
    _stop = {"about", "their", "there", "which", "these", "those", "would", "could",
             "should", "after", "before", "while", "where", "every", "other"}
    script_tags = [w for w, c in sorted(freq.items(), key=lambda x: -x[1]) if w not in _stop][:10]

    all_tags: list[str] = (
            _BASE_TAGS + _NICHE_TAGS.get(niche, []) + topic_tags + script_tags
            + (extra or []) + ["shorts", "viral", "facts", "didyouknow"]
    )

    seen: set[str] = set()
    final: list[str] = []
    for t in all_tags:
        if t.lower() not in seen:
            seen.add(t.lower())
            final.append(t)
    return final[:30]


def build_metadata_from_script(
        topic: str,
        script: str,
        category_id: Optional[str] = None,
        extra_tags: Optional[list[str]] = None,
) -> dict:
    """
    Auto-generate complete YouTube metadata from pipeline outputs.
    Returns a dict that unpacks into upload_short():
        upload_short(video_path, **build_metadata_from_script(topic, script))
    """
    niche = _detect_niche(topic, script)
    log.info(f"Detected niche: {niche}")
    return {
        "title"      : _build_title(topic),
        "description": _build_description(topic, script, niche),
        "tags"       : _build_tags(topic, script, niche, extra_tags),
        "category_id": category_id or CATEGORY.get(niche, CATEGORY["education"]),
    }


# =============================================================================
# CLI — first-time auth or test upload
# =============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if len(sys.argv) == 1:
        print("Auth-only mode — authenticating and saving token…")
        _build_service()
        print("Done. credentials/token.json saved. Future runs will be silent.")
        sys.exit(0)

    if len(sys.argv) < 3:
        print("Usage: python youtube_uploader.py <video.mp4> <title> [publish_at_iso_string]")
        sys.exit(1)

    # Example usage for testing scheduled uploads
    publish_at_str = None
    if len(sys.argv) > 3:
        publish_at_str = sys.argv[3]
        print(f"Scheduling upload for: {publish_at_str}")

    vid_id = upload_short(
        video_path  = sys.argv[1],
        title       = sys.argv[2],
        description = "Test upload from AI Shorts Factory.",
        tags        = ["test"],
        privacy     = "private", # Privacy will be overridden to 'private' if publish_at is set
        publish_at  = publish_at_str,
    )
    print(f"\nUploaded → https://www.youtube.com/shorts/{vid_id}")
