"""
channel_analytics.py — Programmatic YouTube Channel Analytics
==============================================================
Fetches everything useful from YOUR channel using two free Google APIs:

  API 1 — YouTube Data API v3    (public data, 10K units/day free)
           → video titles, tags, duration, view/like/comment counts
           → already partially used by your youtube_uploader.py

  API 2 — YouTube Analytics API  (private data, free, same OAuth creds)
           → average view duration %, average view percentage (retention)
           → CTR from impressions, traffic sources breakdown
           → subscriber gain/loss per video
           → audience demographics

Both APIs use the SAME credentials/client_secrets.json you already have.
You just need to add one extra scope the first time you run this.

QUICK START:
    # First run — will open browser for OAuth (adds analytics scope)
    python -m pipeline.channel_analytics --auth

    # Daily use — pulls last 28 days and saves to CSV + prints summary
    python -m pipeline.channel_analytics

    # Pull specific date range
    python -m pipeline.channel_analytics --days 90

    # Find your best and worst videos
    python -m pipeline.channel_analytics --rank

    # Continuous mode — runs every 6 hours and appends to CSV
    python -m pipeline.channel_analytics --watch
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger("pipeline.channel_analytics")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

# ── Paths ─────────────────────────────────────────────────────────────────────
CREDENTIALS_FILE    = Path("credentials/client_secrets.json")
TOKEN_FILE          = Path("credentials/analytics_token.json")   # separate token from uploader
REPORTS_DIR         = Path("assets/analytics")
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# ── OAuth scopes needed ───────────────────────────────────────────────────────
# Note: we use a SEPARATE token file from the uploader so we don't break uploads
SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",       # Data API
    "https://www.googleapis.com/auth/yt-analytics.readonly",  # Analytics API
]

# ── Constants ─────────────────────────────────────────────────────────────────
DATA_API_BASE      = "https://www.googleapis.com/youtube/v3"
ANALYTICS_API_BASE = "https://youtubeanalytics.googleapis.com/v2"


# =============================================================================
# AUTHENTICATION
# =============================================================================

def get_credentials(force_reauth: bool = False):
    """
    Get valid OAuth credentials.
    Reuses token if valid; opens browser for new auth if needed.
    Uses a SEPARATE token file from your uploader to avoid conflicts.
    """
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request

    creds = None

    if TOKEN_FILE.exists() and not force_reauth:
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                log.info("Token refreshed successfully.")
            except Exception:
                creds = None  # force re-auth

        if not creds:
            if not CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    f"OAuth client secrets not found at {CREDENTIALS_FILE}\n"
                    "Download from: https://console.cloud.google.com/apis/credentials\n"
                    "Make sure YouTube Data API v3 AND YouTube Analytics API are enabled."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), SCOPES
            )
            creds = flow.run_local_server(port=0, open_browser=True)
            log.info("New OAuth token saved.")

        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(creds.to_json())

    return creds


# =============================================================================
# API CLIENTS
# =============================================================================

def build_clients(creds):
    """Build authenticated API client objects."""
    from googleapiclient.discovery import build
    import googleapiclient.discovery

    # Suppress the noisy discovery cache warnings
    import logging as _l
    _l.getLogger("googleapiclient.discovery_cache").setLevel(_l.ERROR)

    data_client      = build("youtube",          "v3",  credentials=creds)
    analytics_client = build("youtubeAnalytics", "v2",  credentials=creds)
    return data_client, analytics_client


# =============================================================================
# STEP 1 — GET YOUR CHANNEL ID
# =============================================================================

def get_my_channel_id(data_client) -> tuple[str, str]:
    """
    Returns (channel_id, channel_title) for the authenticated account.
    This is the channel_id used in all subsequent API calls.
    """
    resp = data_client.channels().list(
        part="id,snippet,statistics",
        mine=True,
    ).execute()

    items = resp.get("items", [])
    if not items:
        raise RuntimeError("No channel found for this account.")

    ch       = items[0]
    ch_id    = ch["id"]
    ch_title = ch["snippet"]["title"]
    stats    = ch.get("statistics", {})

    log.info(f"Channel: {ch_title} (ID: {ch_id})")
    log.info(f"  Subscribers: {int(stats.get('subscriberCount', 0)):,}")
    log.info(f"  Total views: {int(stats.get('viewCount', 0)):,}")
    log.info(f"  Total videos: {int(stats.get('videoCount', 0)):,}")

    return ch_id, ch_title


# =============================================================================
# STEP 2 — LIST ALL YOUR SHORTS (Data API v3)
# =============================================================================

def get_all_videos(data_client, channel_id: str, max_results: int = 200) -> list[dict]:
    """
    Fetch all PUBLIC videos from your channel using YouTube Data API v3.
    Returns a list of dicts with: video_id, title, published_at, duration,
    view_count, like_count, comment_count, tags, description.

    Cost: ~3 units per page (50 videos). 200 videos = ~12 units.
    Free quota: 10,000 units/day — this is negligible.
    """
    log.info("Fetching video list from YouTube Data API...")

    # Step 2a: Get video IDs from the channel's uploads playlist
    # First get the uploads playlist ID
    ch_resp = data_client.channels().list(
        part="contentDetails",
        id=channel_id,
    ).execute()

    uploads_playlist_id = (
        ch_resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    )

    video_ids = []
    page_token = None

    while len(video_ids) < max_results:
        pl_resp = data_client.playlistItems().list(
            part="contentDetails",
            playlistId=uploads_playlist_id,
            maxResults=50,
            pageToken=page_token,
        ).execute()

        for item in pl_resp.get("items", []):
            video_ids.append(item["contentDetails"]["videoId"])

        page_token = pl_resp.get("nextPageToken")
        if not page_token:
            break

    log.info(f"Found {len(video_ids)} videos. Fetching details...")

    # Step 2b: Batch fetch video details (50 per request)
    videos = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i : i + 50]
        vids_resp = data_client.videos().list(
            part="snippet,statistics,contentDetails,status", # Request 'status' part
            id=",".join(batch),
        ).execute()

        for item in vids_resp.get("items", []):
            status      = item.get("status", {})
            # Only include public videos
            if status.get("privacyStatus") != "public":
                continue

            snippet     = item.get("snippet", {})
            stats       = item.get("statistics", {})
            content     = item.get("contentDetails", {})
            duration_iso = content.get("duration", "PT0S")

            # Parse ISO 8601 duration to seconds
            duration_sec = _parse_duration(duration_iso)

            videos.append({
                "video_id":      item["id"],
                "title":         snippet.get("title", ""),
                "published_at":  snippet.get("publishedAt", "")[:10],  # YYYY-MM-DD
                "duration_sec":  duration_sec,
                "is_short":      duration_sec <= 180,  # Shorts ≤ 3 minutes
                "view_count":    int(stats.get("viewCount", 0)),
                "like_count":    int(stats.get("likeCount", 0)),
                "comment_count": int(stats.get("commentCount", 0)),
                "tags":          snippet.get("tags", []),
                "description":   snippet.get("description", "")[:200],
            })

    # Sort by published date descending
    videos.sort(key=lambda v: v["published_at"], reverse=True)
    log.info(f"Fetched details for {len(videos)} public videos.")
    return videos


def _parse_duration(iso: str) -> int:
    """Parse ISO 8601 duration (PT1M30S) to total seconds."""
    import re
    pattern = r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?"
    m = re.match(pattern, iso)
    if not m:
        return 0
    h, mn, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mn * 60 + s


# =============================================================================
# STEP 3 — GET ANALYTICS PER VIDEO (Analytics API)
# =============================================================================

def get_video_analytics(
        analytics_client,
        channel_id: str,
        video_ids: list[str],
        start_date: str,
        end_date: str,
) -> dict[str, dict]:
    """
    Fetch detailed analytics for each video using YouTube Analytics API.

    Returns: {video_id: {metric: value, ...}}

    Metrics fetched:
      - views                      (total views in date range)
      - estimatedMinutesWatched    (total watch time)
      - averageViewDuration        (avg seconds watched per view)
      - averageViewPercentage      (% of video watched — THE key metric)
      - likes
      - subscribersGained
      - subscribersLost
      - annotationClickThroughRate (CTR on cards/end screens)
      - cardClickRate              (CTR on info cards)

    Rate limit: 0 quota cost (Analytics API has separate free quota).
    """
    log.info(f"Fetching analytics for {len(video_ids)} videos ({start_date} → {end_date})...")
    results = {}

    for i, vid_id in enumerate(video_ids):
        # We must query one video at a time when using dimensions="video"
        ids_filter = f"video=={vid_id}"

        try:
            resp = analytics_client.reports().query(
                ids=f"channel=={channel_id}",
                startDate=start_date,
                endDate=end_date,
                metrics=(
                    "views,"
                    "estimatedMinutesWatched,"
                    "averageViewDuration,"
                    "averageViewPercentage,"
                    "likes,"
                    "subscribersGained,"
                    "subscribersLost"
                ),
                dimensions="video",
                filters=ids_filter,
                sort="-views",
            ).execute()

            headers = [h["name"] for h in resp.get("columnHeaders", [])]
            for row in resp.get("rows", []):
                row_dict = dict(zip(headers, row))
                fetched_vid_id = row_dict.pop("video")
                results[fetched_vid_id] = {
                    "views":              int(row_dict.get("views", 0)),
                    "watch_minutes":      round(float(row_dict.get("estimatedMinutesWatched", 0)), 1),
                    "avg_view_sec":       round(float(row_dict.get("averageViewDuration", 0)), 1),
                    "avg_view_pct":       round(float(row_dict.get("averageViewPercentage", 0)), 1),
                    "likes":              int(row_dict.get("likes", 0)),
                    "subs_gained":        int(row_dict.get("subscribersGained", 0)),
                    "subs_lost":          int(row_dict.get("subscribersLost", 0)),
                }

        except Exception as exc:
            log.debug(f"Analytics for video {vid_id} failed or returned no data: {exc}")

        # Be gentle with the API, especially since we are making one call per video
        time.sleep(0.1)
        
        if (i + 1) % 10 == 0:
            log.info(f"  ...processed {i + 1}/{len(video_ids)} videos")

    log.info(f"Analytics fetched for {len(results)} videos.")
    return results


# =============================================================================
# STEP 4 — GET TRAFFIC SOURCES (Analytics API)
# =============================================================================

def get_traffic_sources(
        analytics_client,
        channel_id: str,
        start_date: str,
        end_date: str,
) -> list[dict]:
    """
    Fetch where your views come from (Shorts feed, search, suggested, etc).
    This is channel-level, not per-video.

    Traffic source types:
      YT_SHORTS_FEED       — Shorts feed (what you want to be high)
      SUBSCRIBER_FEED      — Subscribers' home feed
      YT_SEARCH            — YouTube search
      SUGGESTED_VIDEOS     — Suggested/related videos
      EXTERNAL             — External websites
      DIRECT_OR_UNKNOWN    — Direct links / unknown
      NO_LINK_EMBEDDED     — Embedded players
    """
    log.info("Fetching traffic source breakdown...")
    try:
        resp = analytics_client.reports().query(
            ids=f"channel=={channel_id}",
            startDate=start_date,
            endDate=end_date,
            metrics="views,estimatedMinutesWatched",
            dimensions="insightTrafficSourceType",
            sort="-views",
        ).execute()

        sources = []
        total_views = sum(int(r[1]) for r in resp.get("rows", []))
        for row in resp.get("rows", []):
            source_views = int(row[1])
            sources.append({
                "source":      row[0],
                "views":       source_views,
                "pct_of_total": round(source_views / total_views * 100, 1) if total_views else 0,
                "watch_min":   round(float(row[2]), 1),
            })
        return sources

    except Exception as exc:
        log.warning(f"Traffic source fetch failed: {exc}")
        return []


# =============================================================================
# STEP 5 — GET AUDIENCE DEMOGRAPHICS (Analytics API)
# =============================================================================

def get_demographics(
        analytics_client,
        channel_id: str,
        start_date: str,
        end_date: str,
) -> dict:
    """
    Fetch age + gender breakdown and top countries.
    Useful for knowing if you're reaching the audience you're targeting.
    """
    results = {"age_gender": [], "countries": []}
    log.info("Fetching audience demographics...")

    # Age + gender
    try:
        resp = analytics_client.reports().query(
            ids=f"channel=={channel_id}",
            startDate=start_date,
            endDate=end_date,
            metrics="viewerPercentage",
            dimensions="ageGroup,gender",
            sort="-viewerPercentage",
        ).execute()
        for row in resp.get("rows", []):
            results["age_gender"].append({
                "age_group": row[0],
                "gender":    row[1],
                "pct":       round(float(row[2]), 1),
            })
    except Exception as exc:
        log.warning(f"Age/gender demographics failed: {exc}")

    # Top countries
    try:
        resp = analytics_client.reports().query(
            ids=f"channel=={channel_id}",
            startDate=start_date,
            endDate=end_date,
            metrics="views,estimatedMinutesWatched",
            dimensions="country",
            sort="-views",
            maxResults=15,
        ).execute()
        total = sum(int(r[2]) for r in resp.get("rows", []))
        for row in resp.get("rows", []):
            results["countries"].append({
                "country":  row[0],
                "views":    int(row[2]),
                "pct":      round(int(row[2]) / total * 100, 1) if total else 0,
            })
    except Exception as exc:
        log.warning(f"Country demographics failed: {exc}")

    return results


# =============================================================================
# STEP 6 — MERGE + SCORE + RANK
# =============================================================================

def merge_and_score(videos: list[dict], analytics: dict[str, dict]) -> list[dict]:
    """
    Merge Data API + Analytics API data into one unified record per video.
    Compute a composite performance score for ranking.

    Score formula (higher = better):
        score = (avg_view_pct * 0.45)          # retention — most important
               + (like_rate * 100 * 0.30)      # engagement rate
               + (sub_rate * 100 * 0.25)       # subscriber conversion
    """
    merged = []
    for v in videos:
        vid_id = v["video_id"]
        a      = analytics.get(vid_id, {})

        views    = a.get("views", v["view_count"])   # prefer analytics (in-range) over lifetime
        likes    = a.get("likes", v["like_count"])
        subs     = a.get("subs_gained", 0)
        avg_pct  = a.get("avg_view_pct", 0.0)
        avg_sec  = a.get("avg_view_sec", 0.0)

        like_rate = likes / views if views > 0 else 0
        sub_rate  = subs  / views if views > 0 else 0

        score = (avg_pct * 0.45) + (like_rate * 100 * 0.30) + (sub_rate * 100 * 0.25)

        merged.append({
            **v,
            "analytics_views":  views,
            "watch_minutes":    a.get("watch_minutes", 0),
            "avg_view_sec":     avg_sec,
            "avg_view_pct":     avg_pct,
            "subs_gained":      subs,
            "subs_lost":        a.get("subs_lost", 0),
            "like_rate_pct":    round(like_rate * 100, 2),
            "sub_rate_pct":     round(sub_rate  * 100, 3),
            "score":            round(score, 3),
            # Derived signals
            "retention_grade":  _grade(avg_pct, [(80,"A+"), (65,"A"), (50,"B"), (35,"C"), (0,"D")]),
            "engagement_grade": _grade(like_rate * 100, [(5,"A+"), (3,"A"), (2,"B"), (1,"C"), (0,"D")]),
        })

    merged.sort(key=lambda x: -x["score"])
    return merged


def _grade(value: float, thresholds: list[tuple]) -> str:
    for threshold, grade in thresholds:
        if value >= threshold:
            return grade
    return "F"


# =============================================================================
# OUTPUT: CSV + CONSOLE REPORT
# =============================================================================

def save_csv(videos: list[dict], filename: str) -> Path:
    """Save all video data to a CSV file for spreadsheet analysis."""
    path = REPORTS_DIR / filename
    if not videos:
        log.warning("No videos to save.")
        return path

    fieldnames = [
        "video_id", "title", "published_at", "duration_sec", "is_short",
        "analytics_views", "view_count", "watch_minutes",
        "avg_view_sec", "avg_view_pct", "retention_grade",
        "like_count", "like_rate_pct", "engagement_grade",
        "subs_gained", "subs_lost", "sub_rate_pct",
        "score", "tags",
    ]

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for v in videos:
            row = dict(v)
            row["tags"] = "|".join(v.get("tags", []))
            writer.writerow(row)

    log.info(f"CSV saved: {path}")
    return path


def save_json(data: dict, filename: str) -> Path:
    """Save raw data to JSON for programmatic access."""
    path = REPORTS_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    log.info(f"JSON saved: {path}")
    return path


def print_console_report(
        videos: list[dict],
        traffic_sources: list[dict],
        demographics: dict,
        days: int,
) -> None:
    """Print a clean analytics summary to the terminal."""
    shorts = [v for v in videos if v.get("is_short")]
    if not shorts:
        print("\nNo Shorts found in this date range.")
        return

    print("\n" + "═" * 65)
    print(f"  CHANNEL ANALYTICS REPORT — last {days} days")
    print("═" * 65)

    total_views   = sum(v["analytics_views"] for v in shorts)
    total_subs    = sum(v["subs_gained"] for v in shorts)
    avg_retention = sum(v["avg_view_pct"] for v in shorts) / len(shorts) if shorts else 0

    print(f"\n  Videos analysed : {len(shorts)}")
    print(f"  Total views     : {total_views:,}")
    print(f"  Total subs      : +{total_subs:,}")
    print(f"  Avg retention   : {avg_retention:.1f}%  {'✓ healthy' if avg_retention > 55 else '✗ needs work'}")

    # Top 5 videos
    print(f"\n  TOP 5 VIDEOS (by score)")
    print(f"  {'Title':<38} {'Views':>7} {'Ret%':>6} {'Grade':>5}")
    print(f"  {'-'*38} {'-'*7} {'-'*6} {'-'*5}")
    for v in shorts[:5]:
        title = v["title"][:36] + ".." if len(v["title"]) > 36 else v["title"]
        print(f"  {title:<38} {v['analytics_views']:>7,} {v['avg_view_pct']:>5.1f}%  {v['retention_grade']:>4}")

    # Bottom 5 videos
    print(f"\n  BOTTOM 5 VIDEOS (worst retention)")
    bottom = sorted(shorts, key=lambda x: x["avg_view_pct"])[:5]
    for v in bottom:
        title = v["title"][:36] + ".." if len(v["title"]) > 36 else v["title"]
        print(f"  {title:<38} {v['analytics_views']:>7,} {v['avg_view_pct']:>5.1f}%  {v['retention_grade']:>4}")

    # Traffic sources
    if traffic_sources:
        print(f"\n  TRAFFIC SOURCES")
        for s in traffic_sources[:6]:
            bar = "█" * int(s["pct_of_total"] / 3)
            print(f"  {s['source']:<28} {s['pct_of_total']:>5.1f}%  {bar}")

    # Top countries
    if demographics.get("countries"):
        print(f"\n  TOP COUNTRIES")
        for c in demographics["countries"][:8]:
            print(f"  {c['country']:<8} {c['views']:>8,} views  ({c['pct']:>5.1f}%)")

    print("\n" + "═" * 65)
    print(f"  Full data saved to: {REPORTS_DIR}/")
    print("═" * 65 + "\n")


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def run(days: int = 28, rank: bool = False, force_reauth: bool = False):
    """
    Main function — fetches all analytics and saves reports.

    Args:
        days:         Look-back window in days (default 28).
        rank:         If True, print detailed ranking of all videos.
        force_reauth: Force new OAuth flow.
    """
    end_date   = date.today().isoformat()
    start_date = (date.today() - timedelta(days=days)).isoformat()

    log.info(f"Fetching analytics: {start_date} → {end_date} ({days} days)")

    # Auth
    creds                    = get_credentials(force_reauth)
    data_client, an_client   = build_clients(creds)

    # Get channel
    channel_id, channel_title = get_my_channel_id(data_client)

    # Get all videos (Data API)
    videos = get_all_videos(data_client, channel_id, max_results=500)
    if not videos:
        log.error("No videos found. Check channel and credentials.")
        return

    # Get analytics (Analytics API)
    video_ids       = [v["video_id"] for v in videos]
    analytics       = get_video_analytics(an_client, channel_id, video_ids, start_date, end_date)
    traffic_sources = get_traffic_sources(an_client, channel_id, start_date, end_date)
    demographics    = get_demographics(an_client, channel_id, start_date, end_date)

    # Merge + score
    ranked = merge_and_score(videos, analytics)

    # Save outputs
    timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path   = save_csv(ranked, f"videos_{timestamp}.csv")
    save_json({
        "channel_id":      channel_id,
        "channel_title":   channel_title,
        "date_range":      {"start": start_date, "end": end_date},
        "traffic_sources": traffic_sources,
        "demographics":    demographics,
        "video_count":     len(ranked),
    }, f"summary_{timestamp}.json")

    # Print report
    print_console_report(ranked, traffic_sources, demographics, days)

    if rank:
        print("\nFULL VIDEO RANKING:")
        print(f"{'#':<4} {'Title':<40} {'Views':>7} {'Ret%':>6} {'Score':>6}")
        print("-" * 70)
        for i, v in enumerate(ranked, 1):
            if v.get("is_short"):
                title = v["title"][:38] + ".." if len(v["title"]) > 38 else v["title"]
                print(f"{i:<4} {title:<40} {v['analytics_views']:>7,} {v['avg_view_pct']:>5.1f}% {v['score']:>6.2f}")

    return ranked, traffic_sources, demographics


def watch_mode(interval_hours: int = 6, days: int = 28):
    """Run analytics continuously every N hours."""
    log.info(f"Watch mode: running every {interval_hours} hours. Ctrl+C to stop.")
    while True:
        try:
            run(days=days)
        except Exception as exc:
            log.error(f"Watch mode error: {exc}")
        log.info(f"Next run in {interval_hours} hours...")
        time.sleep(interval_hours * 3600)


# =============================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="YouTube Channel Analytics — programmatic data fetcher"
    )
    parser.add_argument(
        "--auth", action="store_true",
        help="Force new OAuth authentication (run this first)"
    )
    parser.add_argument(
        "--days", type=int, default=28,
        help="Look-back window in days (default: 28)"
    )
    parser.add_argument(
        "--rank", action="store_true",
        help="Print full ranking of all videos"
    )
    parser.add_argument(
        "--watch", action="store_true",
        help="Run continuously every 6 hours"
    )
    parser.add_argument(
        "--interval", type=int, default=6,
        help="Hours between runs in watch mode (default: 6)"
    )
    args = parser.parse_args()

    if args.watch:
        watch_mode(interval_hours=args.interval, days=args.days)
    else:
        run(days=args.days, rank=args.rank, force_reauth=args.auth)