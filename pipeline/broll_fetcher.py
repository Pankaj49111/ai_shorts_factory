"""
broll_fetcher.py  —  AI Shorts Factory
========================================
Downloads portrait b-roll clips from Pexels.

Changes vs original:
- Added `output_dir` param so each run saves clips to its own folder
  instead of a shared assets/broll/ dir that gets overwritten.
- If output_dir is None, falls back to original assets/broll/ behaviour.
"""

from __future__ import annotations

import os
import logging
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
PEXELS_VIDEO_URL = "https://api.pexels.com/videos/search"


def download_broll(
        queries: list[str],
        clips_per_query: int = 1,
        output_dir: str | None = None,
) -> list[str]:
 """
 Download one portrait video clip per query from Pexels.

 Parameters
 ----------
 queries        : list of search terms
 clips_per_query: how many clips to fetch per query (keep 1 for variety)
 output_dir     : directory to save clips into.
                  Defaults to assets/broll/ if None.

 Returns
 -------
 List of local file paths for downloaded clips.
 """
 if not PEXELS_API_KEY:
  raise ValueError("PEXELS_API_KEY is not set in .env")

 save_dir = Path(output_dir) if output_dir else Path("assets/broll")
 save_dir.mkdir(parents=True, exist_ok=True)

 headers  = {"Authorization": PEXELS_API_KEY}
 paths: list[str] = []

 for i, query in enumerate(queries):
  params = {
   "query"      : query,
   "per_page"   : clips_per_query + 2,   # fetch a couple of extras to filter
   "orientation": "portrait",
   "size"       : "medium",
  }
  try:
   resp = requests.get(PEXELS_VIDEO_URL, headers=headers, params=params, timeout=20)
   resp.raise_for_status()
   videos = resp.json().get("videos", [])
  except Exception as exc:
   log.warning(f"Pexels query '{query}' failed: {exc}")
   continue

  for vid in videos[:clips_per_query]:
   # Pick the highest-quality file that is portrait
   files = sorted(
    [f for f in vid.get("video_files", []) if f.get("height", 0) > f.get("width", 0)],
    key=lambda f: f.get("height", 0),
    reverse=True,
   )
   if not files:
    # Fallback to first file available
    files = vid.get("video_files", [])
   if not files:
    log.warning(f"No files for video id {vid.get('id')} on query '{query}'")
    continue

   link = files[0]["link"]
   fname = save_dir / f"clip_{i}.mp4"

   try:
    with requests.get(link, stream=True, timeout=60) as r:
     r.raise_for_status()
     with open(fname, "wb") as f:
      for chunk in r.iter_content(chunk_size=1024 * 256):
       f.write(chunk)
    log.info(f"Downloaded: {fname} (query='{query}')")
    paths.append(str(fname))
   except Exception as exc:
    log.warning(f"Download failed for '{query}': {exc}")

 return paths