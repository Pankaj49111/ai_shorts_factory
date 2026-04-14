"""
instagram_uploader.py — Instagram Reels Uploader via Meta Graph API
====================================================================
Uploads a local video file as an Instagram Reel using the official
Meta Graph API (Content Publishing API).

HOW THE API WORKS (simplified):
  Step 1: Upload video bytes to Meta's servers → get a media container ID
  Step 2: Tell Instagram to publish that container as a Reel

The video must reach Meta's servers. This module handles two methods:
  Method A (PRIMARY):   Direct binary upload via resumable upload session
  Method B (FALLBACK):  Public URL (only if you have a web server / ngrok)

PREREQUISITES (all explained in INSTAGRAM_SETUP_GUIDE.md):
  - INSTAGRAM_ACCOUNT_ID     (your IG professional account numeric ID)
  - INSTAGRAM_ACCESS_TOKEN   (long-lived User access token with publish perms)

Usage:
    from pipeline.instagram_uploader import upload_reel
    result = upload_reel(
        video_path="assets/runs/20260401/output.mp4",
        caption="Why your brain makes bad decisions at night.\n\n#psychology",
        cluster="PSYCHOLOGY",
    )
    print(result)  # {"reel_id": "17...", "permalink": "https://www.instagram.com/reel/..."}
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Optional

import requests

log = logging.getLogger("pipeline.instagram_uploader")

# ── Config (loaded from .env) ─────────────────────────────────────────────────
IG_ACCOUNT_ID   = os.getenv("INSTAGRAM_ACCOUNT_ID")    # numeric string e.g. "17841400000000000"
ACCESS_TOKEN    = os.getenv("INSTAGRAM_ACCESS_TOKEN")  # long-lived token

# GRAPH_BASE      = "https://graph.facebook.com/v21.0"
GRAPH_BASE_FB = "https://graph.facebook.com/v21.0"    # for media publish
GRAPH_BASE_IG = "https://graph.instagram.com/v21.0"   # for account queries
PUBLISH_TIMEOUT = 300   # seconds to wait for Instagram to process video
POLL_INTERVAL   = 10    # seconds between status checks

# Cluster-specific hashtag banks for maximum discovery
_CLUSTER_HASHTAGS: dict[str, str] = {
    "AI_TECH": (
        "#AI #ArtificialIntelligence #TechFacts #AIFacts #Technology "
        "#MachineLearning #FutureTech #AITools #TechShorts #LearnAI"
    ),
    "PSYCHOLOGY": (
        "#Psychology #BrainFacts #Neuroscience #MentalHealth #MindFacts "
        "#HumanBrain #PsychologyFacts #BrainScience #SelfImprovement #Mindset"
    ),
    "FINANCE": (
        "#Finance #MoneyFacts #PersonalFinance #FinancialFreedom #Investing "
        "#WealthBuilding #MoneyTips #FinancialLiteracy #SaveMoney #MoneyMindset"
    ),
    "SCIENCE": (
        "#Science #ScientificFacts #SpaceFacts #NatureFacts #Biology "
        "#Universe #HumanBody #ScienceDaily #MindBlowing #DidYouKnow"
    ),
}

_BASE_HASHTAGS = "#Shorts #Reels #Facts #LearnOnInstagram #Educational"


# ─────────────────────────────────────────────────────────────────────────────
# Helper: validate environment
# ─────────────────────────────────────────────────────────────────────────────

def _validate_env() -> None:
    missing = []
    if not IG_ACCOUNT_ID:
        missing.append("INSTAGRAM_ACCOUNT_ID")
    if not ACCESS_TOKEN:
        missing.append("INSTAGRAM_ACCESS_TOKEN")
    if missing:
        raise RuntimeError(
            f"Missing required env vars: {', '.join(missing)}\n"
            f"Add them to your .env file. See INSTAGRAM_SETUP_GUIDE.md."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Step 1: Create media container via resumable upload
# ─────────────────────────────────────────────────────────────────────────────

def _create_upload_session(video_path: Path) -> str:
    """
    Start a resumable upload session with Meta.
    Returns the upload_url to POST the video bytes to.
    """
    file_size = video_path.stat().st_size
    log.info(f"[instagram] Creating upload session for {file_size:,} byte file")

    url = f"{GRAPH_BASE_FB}/{IG_ACCOUNT_ID}/media"
    params = {
        "media_type":     "REELS",
        "upload_type":    "resumable",
        "access_token":   ACCESS_TOKEN,
    }
    resp = requests.post(url, params=params, timeout=30)
    _check_response(resp, "create upload session")

    data = resp.json()
    upload_url = data.get("uri")
    if not upload_url:
        raise RuntimeError(f"No upload URI in response: {data}")

    log.info(f"[instagram] Upload session created. URI obtained.")
    return upload_url


def _upload_video_bytes(upload_url: str, video_path: Path) -> None:
    """
    Upload the actual video bytes to Meta's resumable upload endpoint.
    """
    file_size = video_path.stat().st_size
    log.info(f"[instagram] Uploading {file_size / 1_048_576:.1f} MB video bytes...")

    with open(video_path, "rb") as f:
        video_bytes = f.read()

    headers = {
        "Authorization":    f"OAuth {ACCESS_TOKEN}",
        "offset":           "0",
        "file_size":        str(file_size),
        "Content-Type":     "application/octet-stream",
    }
    resp = requests.post(upload_url, headers=headers, data=video_bytes, timeout=120)
    _check_response(resp, "upload video bytes")
    log.info(f"[instagram] Video bytes uploaded successfully.")


def _create_reel_container(
        video_path: Path,
        caption: str,
        cover_url: Optional[str] = None,
) -> str:
    """
    Create the Reel media container using resumable upload.
    Returns the ig_container_id needed for publishing.
    """
    # Step 1a: Open upload session
    upload_url = _create_upload_session(video_path)

    # Step 1b: Upload the bytes
    _upload_video_bytes(upload_url, video_path)

    # Step 1c: Create media object (links container to uploaded bytes)
    url = f"{GRAPH_BASE_FB}/{IG_ACCOUNT_ID}/media"
    payload = {
        "media_type":   "REELS",
        "video_url":    upload_url,    # reference to uploaded bytes
        "caption":      caption,
        "share_to_feed": "true",       # also appears in main feed grid
        "access_token": ACCESS_TOKEN,
    }
    if cover_url:
        payload["thumb_offset"] = "1000"   # 1 second in as thumbnail

    resp = requests.post(url, data=payload, timeout=60)
    _check_response(resp, "create reel container")

    container_id = resp.json().get("id")
    if not container_id:
        raise RuntimeError(f"No container ID returned: {resp.json()}")

    log.info(f"[instagram] Reel container created: {container_id}")
    return container_id


# ─────────────────────────────────────────────────────────────────────────────
# Step 2: Wait for processing, then publish
# ─────────────────────────────────────────────────────────────────────────────

def _wait_for_processing(container_id: str) -> None:
    """
    Poll the container status until Instagram finishes processing the video.
    Instagram typically takes 30–120 seconds for a 60-second Reel.
    """
    log.info(f"[instagram] Waiting for video processing (up to {PUBLISH_TIMEOUT}s)...")
    url = f"{GRAPH_BASE_FB}/{container_id}"
    params = {
        "fields":       "status_code,status",
        "access_token": ACCESS_TOKEN,
    }

    deadline = time.time() + PUBLISH_TIMEOUT
    while time.time() < deadline:
        resp = requests.get(url, params=params, timeout=30)
        _check_response(resp, "check processing status")

        data        = resp.json()
        status_code = data.get("status_code", "")
        status      = data.get("status", "")

        log.info(f"[instagram] Status: {status_code} | {status}")

        if status_code == "FINISHED":
            log.info("[instagram] Video processing complete.")
            return

        if status_code in ("ERROR", "EXPIRED"):
            raise RuntimeError(
                f"Instagram processing failed: status_code={status_code}, "
                f"status={status}\n"
                f"Common causes: video codec not H.264, audio not AAC, "
                f"resolution not 9:16 aspect ratio."
            )

        time.sleep(POLL_INTERVAL)

    raise RuntimeError(
        f"Video processing timed out after {PUBLISH_TIMEOUT}s. "
        f"Container ID: {container_id}"
    )


def _publish_container(container_id: str) -> str:
    """
    Publish the processed container as a live Reel.
    Returns the published media ID.
    """
    log.info(f"[instagram] Publishing Reel container {container_id}...")
    url = f"{GRAPH_BASE_FB}/{IG_ACCOUNT_ID}/media_publish"
    payload = {
        "creation_id":  container_id,
        "access_token": ACCESS_TOKEN,
    }

    resp = requests.post(url, data=payload, timeout=30)
    _check_response(resp, "publish reel")

    media_id = resp.json().get("id")
    if not media_id:
        raise RuntimeError(f"No media ID in publish response: {resp.json()}")

    log.info(f"[instagram] Published! Media ID: {media_id}")
    return media_id


def _get_permalink(media_id: str) -> str:
    """Fetch the public permalink for the published Reel."""
    url = f"{GRAPH_BASE_IG}/{media_id}"
    params = {
        "fields":       "permalink,shortcode",
        "access_token": ACCESS_TOKEN,
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()
        return data.get("permalink", f"https://www.instagram.com/reel/{data.get('shortcode','')}/")
    except Exception:
        return f"https://www.instagram.com/"


# ─────────────────────────────────────────────────────────────────────────────
# Error handler
# ─────────────────────────────────────────────────────────────────────────────

def _check_response(resp: requests.Response, step: str) -> None:
    """Raise a clear error if the API returned a non-2xx or error JSON."""
    try:
        data = resp.json()
    except Exception:
        data = {}

    if resp.status_code == 429:
        # Rate limited — Meta allows 25 API calls/hour per token
        retry_after = int(resp.headers.get("Retry-After", 60))
        raise RuntimeError(
            f"[instagram] Rate limited at step '{step}'. "
            f"Retry after {retry_after}s. "
            f"Meta allows 25 API calls/hour per token."
        )

    if "error" in data:
        err = data["error"]
        code    = err.get("code", "?")
        subcode = err.get("error_subcode", "")
        msg     = err.get("message", "Unknown error")
        raise RuntimeError(
            f"[instagram] API error at step '{step}': "
            f"code={code} subcode={subcode} message={msg}\n"
            f"Full error: {err}"
        )

    if not resp.ok:
        raise RuntimeError(
            f"[instagram] HTTP {resp.status_code} at step '{step}': {resp.text[:500]}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Caption builder
# ─────────────────────────────────────────────────────────────────────────────

def build_instagram_caption(
        script_summary: str,
        topic: str,
        cluster: str = "SCIENCE",
) -> str:
    """
    Build an Instagram caption with the script summary, a CTA, and hashtags.
    Instagram caption limit: 2,200 characters.

    Args:
        script_summary: First 1-2 sentences of the script (used as caption hook)
        topic:          Video topic (used in caption body)
        cluster:        Niche cluster (used to select hashtag bank)

    Returns:
        Formatted caption string ready for the API.
    """
    cluster_tags = _CLUSTER_HASHTAGS.get(cluster, _CLUSTER_HASHTAGS["SCIENCE"])
    all_hashtags = f"{cluster_tags} {_BASE_HASHTAGS}".strip()

    caption = (
        f"{script_summary}\n\n"
        f"Follow for more facts like this every day.\n\n"
        f"{all_hashtags}"
    )

    # Enforce Instagram's 2,200 char limit (keep hashtags, trim summary if needed)
    if len(caption) > 2200:
        max_summary = 2200 - len(all_hashtags) - 60
        caption = (
            f"{script_summary[:max_summary].rstrip()}...\n\n"
            f"Follow for more facts like this every day.\n\n"
            f"{all_hashtags}"
        )

    return caption


# ─────────────────────────────────────────────────────────────────────────────
# Public API: upload_reel()
# ─────────────────────────────────────────────────────────────────────────────

def upload_reel(
        video_path: str,
        caption: str,
        cluster: str = "SCIENCE",
        max_retries: int = 3,
) -> dict:
    """
    Upload a local video file as an Instagram Reel.

    Args:
        video_path:  Absolute or relative path to the .mp4 file.
        caption:     Full caption text (include hashtags).
        cluster:     Niche cluster (for logging only at this level).
        max_retries: Number of retry attempts on transient errors.

    Returns:
        dict with keys: reel_id, permalink, cluster

    Raises:
        RuntimeError: On permanent API errors or exhausted retries.
    """
    _validate_env()

    path = Path(video_path)
    if not path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    # Video requirements check (warn, don't block)
    size_mb = path.stat().st_size / 1_048_576
    if size_mb > 1000:
        log.warning(f"[instagram] Video is {size_mb:.0f}MB. Max is 1GB.")
    if size_mb < 0.1:
        log.warning(f"[instagram] Video is very small ({size_mb:.1f}MB). Check encoding.")

    log.info(f"[instagram] Starting Reel upload: {path.name} ({size_mb:.1f}MB)")
    log.info(f"[instagram] Cluster: {cluster}")

    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            # ── Step 1: Create container (upload bytes + register metadata) ──
            container_id = _create_reel_container(path, caption)

            # ── Step 2: Wait for Instagram to process the video ──────────────
            _wait_for_processing(container_id)

            # ── Step 3: Publish ───────────────────────────────────────────────
            media_id  = _publish_container(container_id)
            permalink = _get_permalink(media_id)

            log.info(f"[instagram] ✓ Reel live: {permalink}")
            return {
                "reel_id":   media_id,
                "permalink": permalink,
                "cluster":   cluster,
            }

        except RuntimeError as exc:
            last_error = exc
            err_str = str(exc)

            # Don't retry on permanent errors
            if any(code in err_str for code in ["code=100", "code=200", "EXPIRED", "codec"]):
                log.error(f"[instagram] Permanent error — not retrying: {exc}")
                raise

            log.warning(
                f"[instagram] Attempt {attempt}/{max_retries} failed: {exc}\n"
                f"Retrying in {30 * attempt}s..."
            )
            time.sleep(30 * attempt)

    raise RuntimeError(
        f"Instagram upload failed after {max_retries} attempts.\n"
        f"Last error: {last_error}"
    )


def is_instagram_configured() -> bool:
    """
    Returns True if all required Instagram env vars are present.
    Used by pipeline_runner.py as a pre-flight check.
    """
    return bool(
        os.getenv("INSTAGRAM_ACCOUNT_ID") and
        os.getenv("INSTAGRAM_ACCESS_TOKEN")
    )