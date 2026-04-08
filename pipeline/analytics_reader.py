"""
analytics_reader.py — YouTube Analytics Feedback Loop v1
=========================================================
Reads your YouTube Analytics API (free, read-only) and produces
a cluster_scores.json file that pipeline_runner.py uses to
bias topic selection toward clusters that are actually performing.

Run this as a SEPARATE weekly job — it does NOT run on every pipeline call.
Add to crontab or GitHub Actions:
    0 9 * * 1  python -m pipeline.analytics_reader   (every Monday 9am)

Outputs:
    assets/logs/cluster_scores.json    ← read by trend_fetcher / pipeline_runner
    assets/logs/analytics_report.csv  ← human-readable weekly report

Requirements:
    Same Google OAuth credentials used for YouTube upload.
    Scopes needed: youtube.readonly + yt-analytics.readonly

The first time you run this, it may prompt for re-authentication if your
existing token does not include the yt-analytics.readonly scope.
Run: python -m pipeline.analytics_reader --reauth
to force a fresh token flow.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger("pipeline.analytics_reader")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")

CREDENTIALS_FILE  = Path("credentials/client_secrets.json")
TOKEN_FILE        = Path("credentials/youtube_token.json")
CLUSTER_SCORES_FILE = Path("assets/logs/cluster_scores.json")
ANALYTICS_CSV       = Path("assets/logs/analytics_report.csv")
UPLOAD_LOG          = Path("assets/logs/upload_log.csv")

# YouTube Analytics API scopes
_SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

_CLUSTERS = ["AI_TECH", "PSYCHOLOGY", "FINANCE", "SCIENCE"]


# ─────────────────────────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────────────────────────

def _get_credentials(force_reauth: bool = False):
    """Return valid Google OAuth credentials (reuse token if possible)."""
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request

    creds = None
    if TOKEN_FILE.exists() and not force_reauth:
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), _SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    f"OAuth client secrets not found at {CREDENTIALS_FILE}.\n"
                    "Follow credentials/SETUP.md to download client_secrets.json."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), _SCOPES
            )
            creds = flow.run_local_server(port=0)
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(creds.to_json())

    return creds


def _build_analytics_service(creds):
    from googleapiclient.discovery import build
    return build("youtubeAnalytics", "v2", credentials=creds)


# ─────────────────────────────────────────────────────────────────────────────
# Upload log reader — maps video_id → cluster
# ─────────────────────────────────────────────────────────────────────────────

def _load_upload_log() -> dict[str, str]:
    """
    Load upload_log.csv and return {video_id: cluster} mapping.
    upload_log.csv format: timestamp,topic,video_id,url[,cluster]
    """
    if not UPLOAD_LOG.exists():
        log.warning(f"Upload log not found at {UPLOAD_LOG}")
        return {}

    video_cluster: dict[str, str] = {}
    with open(UPLOAD_LOG, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 3:
                continue
            video_id = row[2].strip()
            # cluster is in column 4 if it exists (added by new pipeline_runner)
            cluster  = row[4].strip() if len(row) >= 5 else "UNKNOWN"
            if video_id:
                video_cluster[video_id] = cluster
    return video_cluster


# ─────────────────────────────────────────────────────────────────────────────
# Analytics fetcher
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_video_stats(
        analytics_svc,
        video_ids: list[str],
        start_date: str,
        end_date: str,
) -> dict[str, dict]:
    """
    Fetch views, averageViewPercentage, likes, estimatedMinutesWatched
    for a list of video IDs from the YouTube Analytics API.

    Returns: {video_id: {metric: value, ...}}
    """
    stats: dict[str, dict] = {}
    # API allows max 200 IDs per call — batch if needed
    batch_size = 50
    for i in range(0, len(video_ids), batch_size):
        batch = video_ids[i : i + batch_size]
        ids_str = ";".join(batch)
        try:
            response = (
                analytics_svc.reports()
                .query(
                    ids="channel==MINE",
                    startDate=start_date,
                    endDate=end_date,
                    metrics="views,likes,averageViewPercentage,estimatedMinutesWatched,subscribersGained",
                    dimensions="video",
                    filters=f"video=={ids_str}",
                )
                .execute()
            )
            rows = response.get("rows", [])
            for row in rows:
                vid_id = row[0]
                stats[vid_id] = {
                    "views":                   int(row[1]),
                    "likes":                   int(row[2]),
                    "averageViewPercentage":   float(row[3]),
                    "estimatedMinutesWatched": float(row[4]),
                    "subscribersGained":       int(row[5]),
                }
        except Exception as exc:
            log.error(f"Analytics API error for batch starting {i}: {exc}")

    return stats


# ─────────────────────────────────────────────────────────────────────────────
# Cluster scoring
# ─────────────────────────────────────────────────────────────────────────────

def _compute_cluster_scores(
        video_stats: dict[str, dict],
        video_cluster: dict[str, str],
) -> dict[str, dict]:
    """
    Aggregate per-video stats by cluster.

    Score formula (composite, higher = better):
      score = (avg_view_pct * 0.40) + (like_rate * 100 * 0.30) + (sub_rate * 100 * 0.30)

    Returns: {cluster: {score, video_count, avg_view_pct, avg_views, ...}}
    """
    cluster_data: dict[str, list[dict]] = {c: [] for c in _CLUSTERS}
    cluster_data["UNKNOWN"] = []

    for vid_id, stats in video_stats.items():
        cluster = video_cluster.get(vid_id, "UNKNOWN")
        cluster_data[cluster].append(stats)

    results: dict[str, dict] = {}
    for cluster, rows in cluster_data.items():
        if not rows:
            results[cluster] = {
                "score": 0.0, "video_count": 0,
                "avg_view_pct": 0.0, "avg_views": 0.0,
                "total_views": 0, "total_subs": 0,
            }
            continue

        n = len(rows)
        total_views = sum(r["views"] for r in rows)
        avg_views   = total_views / n
        avg_view_pct = sum(r["averageViewPercentage"] for r in rows) / n
        total_likes  = sum(r["likes"] for r in rows)
        total_subs   = sum(r["subscribersGained"] for r in rows)
        like_rate    = total_likes / total_views if total_views else 0
        sub_rate     = total_subs  / total_views if total_views else 0

        score = (avg_view_pct * 0.40) + (like_rate * 100 * 0.30) + (sub_rate * 100 * 0.30)

        results[cluster] = {
            "score":        round(score, 4),
            "video_count":  n,
            "avg_view_pct": round(avg_view_pct, 2),
            "avg_views":    round(avg_views, 1),
            "total_views":  total_views,
            "total_likes":  total_likes,
            "total_subs":   total_subs,
            "like_rate_pct": round(like_rate * 100, 3),
            "sub_rate_pct":  round(sub_rate * 100, 3),
        }

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Report writer
# ─────────────────────────────────────────────────────────────────────────────

def _write_csv_report(cluster_scores: dict[str, dict], end_date: str):
    ANALYTICS_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(ANALYTICS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "week_ending", "cluster", "score", "video_count",
            "avg_view_pct", "avg_views", "total_views",
            "total_likes", "total_subs", "like_rate_pct", "sub_rate_pct",
        ])
        for cluster, data in sorted(
                cluster_scores.items(), key=lambda x: -x[1]["score"]
        ):
            writer.writerow([
                end_date, cluster,
                data["score"], data["video_count"],
                data["avg_view_pct"], data["avg_views"],
                data["total_views"], data["total_likes"],
                data["total_subs"], data["like_rate_pct"], data["sub_rate_pct"],
            ])
    log.info(f"Analytics CSV written: {ANALYTICS_CSV}")


def _write_cluster_scores_json(cluster_scores: dict[str, dict]):
    """
    Write the machine-readable scores file consumed by pipeline_runner.py
    to bias cluster selection toward top performers.
    """
    CLUSTER_SCORES_FILE.parent.mkdir(parents=True, exist_ok=True)
    out = {
        "generated_at": date.today().isoformat(),
        "clusters":     cluster_scores,
        "ranking": sorted(
            [c for c in _CLUSTERS if cluster_scores.get(c, {}).get("video_count", 0) > 0],
            key=lambda c: -cluster_scores[c]["score"],
        ),
    }
    with open(CLUSTER_SCORES_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    log.info(f"Cluster scores written: {CLUSTER_SCORES_FILE}")

    # Log readable summary
    log.info("=" * 50)
    log.info("CLUSTER PERFORMANCE RANKING (best → worst):")
    for rank, cluster in enumerate(out["ranking"], 1):
        d = cluster_scores[cluster]
        log.info(
            f"  #{rank} {cluster:12s} | score={d['score']:.2f} | "
            f"avg_view_pct={d['avg_view_pct']}% | "
            f"avg_views={d['avg_views']:.0f} | videos={d['video_count']}"
        )
    log.info("=" * 50)


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def run(force_reauth: bool = False, days: int = 28):
    """
    Pull analytics for the last `days` days and update cluster_scores.json.

    Args:
        force_reauth: Force new OAuth flow (use if token lacks analytics scope).
        days:         Look-back window in days (default 28 = 4 weeks).
    """
    end_date   = date.today().isoformat()
    start_date = (date.today() - timedelta(days=days)).isoformat()
    log.info(f"Fetching analytics: {start_date} → {end_date}")

    creds           = _get_credentials(force_reauth)
    analytics_svc   = _build_analytics_service(creds)
    video_cluster   = _load_upload_log()

    if not video_cluster:
        log.warning("No videos in upload log yet. Run the pipeline first.")
        return

    video_ids = list(video_cluster.keys())
    log.info(f"Fetching stats for {len(video_ids)} videos across {days} days...")

    video_stats     = _fetch_video_stats(analytics_svc, video_ids, start_date, end_date)
    cluster_scores  = _compute_cluster_scores(video_stats, video_cluster)

    _write_csv_report(cluster_scores, end_date)
    _write_cluster_scores_json(cluster_scores)

    log.info("Analytics update complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="YouTube Analytics Feedback Loop")
    parser.add_argument("--reauth", action="store_true",
                        help="Force fresh OAuth flow to add analytics scope")
    parser.add_argument("--days", type=int, default=28,
                        help="Number of days to look back (default 28)")
    args = parser.parse_args()
    run(force_reauth=args.reauth, days=args.days)