"""
pipeline_runner.py  —  AI Shorts Factory  (v4 — fully hardened)
================================================================
Entry point:  python pipeline_runner.py

Per-run isolated dirs:
    assets/runs/<YYYYMMDD_HHMMSS>/
        narration.mp3  |  broll/  |  script.txt  |  output.mp4  |  meta.json

Eviction: keeps the 2 newest runs; older ones are auto-deleted.
"""

from __future__ import annotations

import json
import logging
import os
import random
import shutil
import sys
import time
from datetime import datetime, timedelta, time as dt_time, date, timezone
from pathlib import Path
from typing import Optional

from pipeline.trend_fetcher     import get_trending_topic
from pipeline.script_generator  import generate_script
from pipeline.script_cleaner    import clean_script
from pipeline.voice_generator   import generate_voice
from pipeline.keyword_extractor import extract_keywords
from pipeline.broll_fetcher     import download_broll
from pipeline.video_assembler   import assemble
from pipeline.youtube_uploader  import upload_short, build_metadata_from_script, is_youtube_configured

from dotenv import load_dotenv
load_dotenv()

try:
    import pytz
except ImportError as exc:
    raise SystemExit(
        "The 'pytz' library is required for timezone handling. Please install it: pip install pytz"
    ) from exc

# =============================================================================
# CONFIG
# =============================================================================

RUNS_ROOT       = Path("assets/runs")
BROLL_CACHE_DIR = Path("assets/broll_cache")
MUSIC_DIR       = Path("assets/music")   # Directory for background music
KEEP_RUNS       = 2 # Keep only the current run and the previous one


TARGET_DURATION  = (20, 32)
MIN_BROLL_CLIPS  = 5
MAX_SCRIPT_WORDS = 85
MIN_SCRIPT_WORDS = 40
WHISPER_MODEL    = "base"
CAPTION_MODE     = "simple" # Changed from "karaoke" to "simple"

# Voice
POPULAR_VOICES = [
    "en-US-JennyNeural",
    "en-US-GuyNeural",
    "en-US-ChristopherNeural",
    "en-CA-ClaraNeural",
    "en-CA-LiamNeural",
    "en-AU-NatashaNeural",
    "en-AU-WilliamMultilingualNeural",
    "en-IE-ConnorNeural",
    "en-IE-EmilyNeural"
]

# B-roll
BROLL_QUERIES    = 5
BROLL_RETRY_WAIT = 15
BROLL_MAX_RETRY  = 3

# YouTube
UPLOAD_TO_YOUTUBE  = True
YOUTUBE_PRIVACY    = "private" # Changed from "public" to "private"
NOTIFY_SUBSCRIBERS = False
YOUTUBE_CATEGORY   = "27"    # 27=Education  28=Science&Tech  24=Entertainment

# Deduplication
SEEN_TOPICS_FILE = Path("assets/logs/seen_topics.txt")
MAX_SEEN_TOPICS  = 20 # Keep only the last N topics for deduplication

# Scheduling
IST = pytz.timezone('Asia/Kolkata')
LAST_SCHEDULED_FILE = Path("assets/logs/last_scheduled_time.txt")
INITIAL_SCHEDULE_DATE = date(2026, 3, 29) # Corrected: Start scheduling from March 29th, 2026
# Updated schedule: 5:00 PM, 7:30 PM, 11:30 PM IST
SCHEDULE_TIMES_IST = [dt_time(17, 0), dt_time(19, 30), dt_time(23, 30)]

# =============================================================================
# Logging
# =============================================================================

Path("assets/logs").mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("assets/logs/pipeline.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("pipeline")

# =============================================================================
# Helpers
# =============================================================================

def _ensure_dirs():
    for d in [RUNS_ROOT, BROLL_CACHE_DIR, Path("assets/logs"), Path("credentials"), MUSIC_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def _evict_old_runs():
    runs = sorted(
        [p for p in RUNS_ROOT.iterdir() if p.is_dir()],
        key=lambda p: p.name,
        reverse=True,
    )
    for old in runs[KEEP_RUNS:]:
        log.info(f"Evicting old run: {old.name}")
        shutil.rmtree(old, ignore_errors=True)


def _load_seen_topics() -> set[str]:
    if SEEN_TOPICS_FILE.exists():
        # Read all topics, take the last MAX_SEEN_TOPICS, and convert to a set of lowercase strings
        all_topics = [t.strip() for t in SEEN_TOPICS_FILE.read_text(encoding="utf-8").splitlines() if t.strip()]
        return {t.lower() for t in all_topics[-MAX_SEEN_TOPICS:]}
    return set()


def _save_seen_topic(topic: str):
    SEEN_TOPICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    # Read existing topics
    existing_topics = []
    if SEEN_TOPICS_FILE.exists():
        existing_topics = [t.strip() for t in SEEN_TOPICS_FILE.read_text(encoding="utf-8").splitlines() if t.strip()]
    
    # Add new topic, ensure uniqueness (case-insensitive) and limit size
    existing_topics.append(topic.strip())
    
    # Use an ordered set to maintain order and uniqueness, then limit
    unique_topics = []
    seen_lower = set()
    for t in reversed(existing_topics): # Process in reverse to easily get the latest unique topics
        if t.lower() not in seen_lower:
            unique_topics.append(t)
            seen_lower.add(t.lower())
    
    # Take the latest MAX_SEEN_TOPICS (which are now at the beginning of unique_topics after reversing)
    final_topics = list(reversed(unique_topics))[-MAX_SEEN_TOPICS:]
    
    with open(SEEN_TOPICS_FILE, "w", encoding="utf-8") as f:
        for t in final_topics:
            f.write(t + "\n")


def _get_cached_broll() -> list[str]:
    return [str(p) for p in BROLL_CACHE_DIR.glob("*.mp4")]


def _cache_broll_clips(clips: list[str]):
    for src in clips:
        dst = BROLL_CACHE_DIR / Path(src).name
        if not dst.exists():
            shutil.copy2(src, dst)


def _build_fallback_clips(needed: int) -> list[str]:
    """
    Pad clip list to `needed` using cached b-roll with ::rev::off= variants
    so the assembler treats each as a visually distinct cut.
    """
    cached = _get_cached_broll()
    if not cached:
        raise RuntimeError(
            "Pexels fetch failed AND broll cache is empty.\n"
            "Run at least one successful pipeline run with network access to seed the cache."
        )
    random.shuffle(cached)
    clips = list(cached)
    while len(clips) < needed:
        base   = random.choice(cached)
        offset = random.randint(1, 8)
        clips.append(f"{base}::rev::off={offset}")
    log.warning(f"Fallback: {needed} clips from cache ({len(cached)} unique sources).")
    return clips[:needed]


def _write_meta(run_dir: Path, data: dict):
    path = run_dir / "meta.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    log.info(f"Meta saved: {path}")


def _append_upload_log(timestamp: str, topic: str, video_id: str):
    path = Path("assets/logs/upload_log.csv")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{timestamp},{topic},{video_id},https://www.youtube.com/shorts/{video_id}\n")
    log.info(f"Upload logged: {path}")


def _get_next_publish_time() -> str:
    """
    Calculates the next YouTube publish time based on a flexible IST schedule.
    Ensures the time is always in the future and advances if previous runs were missed.
    Returns the time in ISO 8601 UTC format.
    """
    current_utc_dt = datetime.now(timezone.utc)
    last_scheduled_utc: Optional[datetime] = None

    # 1. Load last scheduled time
    if LAST_SCHEDULED_FILE.exists():
        try:
            with open(LAST_SCHEDULED_FILE, "r", encoding="utf-8") as f:
                last_scheduled_str = f.read().strip()
                if last_scheduled_str:
                    # Ensure it's parsed as timezone-aware UTC
                    last_scheduled_utc = datetime.fromisoformat(last_scheduled_str).replace(tzinfo=timezone.utc)
        except Exception as e:
            log.warning(f"Could not read last scheduled time from {LAST_SCHEDULED_FILE}: {e}. Starting fresh.")

    # 2. Determine the base for calculation
    if last_scheduled_utc is None:
        # First run, start from INITIAL_SCHEDULE_DATE at the first scheduled time slot
        base_dt_ist = IST.localize(datetime.combine(INITIAL_SCHEDULE_DATE, SCHEDULE_TIMES_IST[0]))
        log.info(f"No previous schedule found. Initializing schedule from {base_dt_ist.strftime('%Y-%m-%d %H:%M IST')}")
    else:
        # Convert last scheduled UTC to IST for calculation
        base_dt_ist = last_scheduled_utc.astimezone(IST)
        log.info(f"Last scheduled (IST): {base_dt_ist.strftime('%Y-%m-%d %H:%M IST')}")

    next_publish_ist = base_dt_ist

    # 3. Advance to the next logical slot
    # Find the index of the current time slot, if it matches exactly
    current_slot_idx = -1
    for i, slot_time in enumerate(SCHEDULE_TIMES_IST):
        if next_publish_ist.hour == slot_time.hour and next_publish_ist.minute == slot_time.minute:
            current_slot_idx = i
            break

    if current_slot_idx != -1:
        # It matched a slot exactly, move to the next one
        next_slot_idx = (current_slot_idx + 1) % len(SCHEDULE_TIMES_IST)
        next_time = SCHEDULE_TIMES_IST[next_slot_idx]
        
        if next_slot_idx == 0:
            # We wrapped around to the first slot, so it's the next day
            next_publish_ist = next_publish_ist + timedelta(days=1)
        
        next_publish_ist = next_publish_ist.replace(hour=next_time.hour, minute=next_time.minute)
    else:
        # It didn't match exactly (e.g., manual edit or first run catch-up)
        # Find the *next* upcoming slot today, or roll over to tomorrow's first slot
        found_slot_today = False
        for slot_time in SCHEDULE_TIMES_IST:
            candidate_dt = next_publish_ist.replace(hour=slot_time.hour, minute=slot_time.minute)
            if candidate_dt > next_publish_ist:
                next_publish_ist = candidate_dt
                found_slot_today = True
                break
        
        if not found_slot_today:
            # All slots for today are past, go to the first slot tomorrow
            next_publish_ist = next_publish_ist + timedelta(days=1)
            next_time = SCHEDULE_TIMES_IST[0]
            next_publish_ist = next_publish_ist.replace(hour=next_time.hour, minute=next_time.minute)


    # 4. Catch-up logic: Ensure next_publish_ist is in the future (at least 5 minutes from now UTC)
    next_publish_utc = next_publish_ist.astimezone(timezone.utc)
    future_buffer = timedelta(minutes=5) 

    while next_publish_utc < (current_utc_dt + future_buffer):
        log.info(f"Calculated schedule {next_publish_ist.strftime('%Y-%m-%d %H:%M IST')} is in the past or too soon. Advancing to next slot...")
        
        # Advance to next slot
        current_slot_idx = -1
        for i, slot_time in enumerate(SCHEDULE_TIMES_IST):
            if next_publish_ist.time() == slot_time:
                current_slot_idx = i
                break
                
        next_slot_idx = (current_slot_idx + 1) % len(SCHEDULE_TIMES_IST)
        next_time = SCHEDULE_TIMES_IST[next_slot_idx]
        
        if next_slot_idx == 0:
             next_publish_ist = next_publish_ist + timedelta(days=1)
             
        next_publish_ist = next_publish_ist.replace(hour=next_time.hour, minute=next_time.minute)
        next_publish_utc = next_publish_ist.astimezone(timezone.utc)

    log.info(f"Next video will be scheduled for: {next_publish_ist.strftime('%Y-%m-%d %H:%M IST')} (UTC: {next_publish_utc.isoformat(timespec='seconds')})")

    # 5. Save the new scheduled time (in UTC)
    LAST_SCHEDULED_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LAST_SCHEDULED_FILE, "w", encoding="utf-8") as f:
        f.write(next_publish_utc.isoformat(timespec='seconds'))

    return next_publish_utc.strftime('%Y-%m-%dT%H:%M:%S.%fZ')


# =============================================================================
# Main pipeline
# =============================================================================

def run_pipeline():
    _ensure_dirs()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir   = RUNS_ROOT / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)
    broll_dir = run_dir / "broll"
    broll_dir.mkdir(exist_ok=True)

    log.info("=" * 56)
    log.info(f"Pipeline run: {timestamp}")
    log.info(f"Run dir     : {run_dir}")
    log.info("=" * 56)

    meta: dict = {"timestamp": timestamp, "run_dir": str(run_dir)}

    # ── Pre-flight: YouTube credentials check ─────────────────────────────────
    # FIX: Check creds ONCE upfront — FileNotFoundError is not transient,
    # don't waste 40 seconds retrying it 3 times inside the upload step.
    yt_ready = False
    if UPLOAD_TO_YOUTUBE:
        yt_ready = is_youtube_configured()
        if not yt_ready:
            log.warning(
                "YouTube upload is DISABLED for this run — credentials not found.\n"
                "  To enable uploads:\n"
                "    1. Follow credentials/SETUP.md\n"
                "    2. Run: python pipeline/youtube_uploader.py  (one-time auth)\n"
                "  Video will be saved locally and can be uploaded manually."
            )

    # ── Step 1: Trending topic ────────────────────────────────────────────────
    log.info("STEP 1 — Fetching trending topic")
    seen  = _load_seen_topics()
    topic = None
    for attempt in range(6):
        try:
            candidate = get_trending_topic(seen) # Pass seen topics to trend_fetcher
            if candidate.strip().lower() not in seen: # This check is now redundant if get_trending_topic filters
                topic = candidate
                break
            log.warning(f"Already used: '{candidate}' — retrying ({attempt+1}/6)")
        except Exception as exc:
            log.error(f"trend_fetcher error: {exc}")
            time.sleep(4)

    if not topic:
        raise RuntimeError("Could not find a fresh topic after 6 attempts.")

    log.info(f"Topic: {topic}")
    meta["topic"] = topic
    _save_seen_topic(topic)

    # ── Step 2: Script generation ─────────────────────────────────────────────
    log.info(f"STEP 2 — Generating script (target: {MIN_SCRIPT_WORDS}-{MAX_SCRIPT_WORDS} words)")
    script = None
    for attempt in range(4):
        try:
            candidate  = generate_script(topic)
            word_count = len(candidate.split())
            # FIX: Max was 110 (= ~44s audio), now 62 (= ~25s audio, fits 20-28s target)
            if MIN_SCRIPT_WORDS <= word_count <= MAX_SCRIPT_WORDS:
                script = candidate
                log.info(f"Script accepted: {word_count} words")
                break
            log.warning(
                f"Script word count {word_count} outside [{MIN_SCRIPT_WORDS}, {MAX_SCRIPT_WORDS}] "
                f"— retrying (attempt {attempt+1}/4)"
            )
        except Exception as exc:
            log.error(f"script_generator error (attempt {attempt+1}): {exc}")
            time.sleep(6)

    if not script:
        raise RuntimeError(
            f"Script generation failed — could not produce a {MIN_SCRIPT_WORDS}-{MAX_SCRIPT_WORDS} "
            "word script after 4 attempts. Check your script_generator prompt."
        )

    (run_dir / "script.txt").write_text(f"TOPIC: {topic}\n\n{script}", encoding="utf-8")
    meta["script"] = script

    # ── Step 3: Voice generation ──────────────────────────────────────────────
    log.info("STEP 3 — Generating voice")
    cleaned = clean_script(script)
    meta["cleaned_script"] = cleaned

    # Randomly select a voice for this run
    selected_voice = random.choice(POPULAR_VOICES)
    log.info(f"Selected voice for this run: {selected_voice}")
    meta["voice"] = selected_voice

    audio_path = run_dir / "narration.mp3"
    for attempt in range(3):
        try:
            generate_voice(cleaned, str(audio_path), selected_voice)
            size = audio_path.stat().st_size
            if size < 5_000:
                raise ValueError(f"Audio suspiciously small: {size} bytes")
            log.info(f"Audio: {size:,} bytes")
            break
        except Exception as exc:
            log.error(f"voice_generator error (attempt {attempt+1}): {exc}")
            time.sleep(5)
    else:
        raise RuntimeError("Voice generation failed after 3 attempts.")

    # ── Step 4a: Keyword extraction ───────────────────────────────────────────
    log.info("STEP 4a — Extracting Pexels keywords")
    queries: list[str] = []
    for attempt in range(3):
        try:
            queries = extract_keywords(script, count=BROLL_QUERIES)
            if queries:
                break
        except Exception as exc:
            log.error(f"keyword_extractor error (attempt {attempt+1}): {exc}")
            time.sleep(5)

    if not queries:
        log.warning("Keyword extraction failed — falling back to topic words.")
        queries = [w.strip(".,!?") for w in topic.split() if len(w) > 3][:BROLL_QUERIES]

    log.info(f"Queries: {queries}")
    meta["broll_queries"] = queries

    # ── Step 4b: B-roll fetch with retry + cache fallback ─────────────────────
    log.info("STEP 4b — Downloading b-roll")
    fresh_clips: list[str] = []

    for attempt in range(BROLL_MAX_RETRY):
        try:
            result = download_broll(queries, clips_per_query=1, output_dir=str(broll_dir))
            if len(result) >= 2:
                fresh_clips = result
                _cache_broll_clips(fresh_clips)
                log.info(f"Downloaded {len(fresh_clips)} fresh clips.")
                break
            log.warning(f"Only {len(result)} clips returned (attempt {attempt+1})")
        except Exception as exc:
            log.warning(f"Pexels error (attempt {attempt+1}): {exc}")

        if attempt < BROLL_MAX_RETRY - 1:
            time.sleep(BROLL_RETRY_WAIT)

    broll = list(fresh_clips)

    if len(broll) < MIN_BROLL_CLIPS:
        needed = MIN_BROLL_CLIPS - len(broll)
        log.warning(f"Only {len(broll)}/{MIN_BROLL_CLIPS} clips — pulling {needed} from cache.")
        broll += _build_fallback_clips(needed)

    log.info(f"Final clip list: {len(broll)} clips")
    meta["broll_clips"] = broll

    # ── Step 5: Video assembly ────────────────────────────────────────────────
    log.info("STEP 5 — Assembling video")
    output_path = run_dir / "output.mp4"

    music_arg = None
    if MUSIC_DIR and MUSIC_DIR.is_dir():
        music_files = [p for p in MUSIC_DIR.glob("*.mp3") if p.is_file()]
        if music_files:
            music_arg = str(random.choice(music_files))
            log.info(f"Selected music: {Path(music_arg).name}")
        else:
            log.warning(f"No .mp3 files found in '{MUSIC_DIR}' — skipping background music.")
    elif MUSIC_DIR:
        log.warning(f"Music directory not found at '{MUSIC_DIR}' — skipping.")


    for attempt in range(2):
        try:
            assemble(
                broll           = broll,
                audio           = str(audio_path),
                outfile         = str(output_path),
                music_path      = music_arg,
                captions        = True,
                whisper_model   = WHISPER_MODEL,
                caption_mode    = CAPTION_MODE,
                target_duration = TARGET_DURATION,
                min_cuts        = MIN_BROLL_CLIPS,
            )
            size = output_path.stat().st_size if output_path.exists() else 0
            if size < 50_000:
                raise ValueError(f"Output video too small ({size} bytes).")
            log.info(f"Video: {size / 1_048_576:.1f} MB → {output_path}")
            break
        except Exception as exc:
            log.error(f"video_assembler error (attempt {attempt+1}): {exc}")
            if attempt == 1:
                raise RuntimeError(f"Video assembly failed: {exc}") from exc
            time.sleep(6)

    meta["output_path"] = str(output_path)

    # ── Step 6: YouTube metadata ──────────────────────────────────────────────
    log.info("STEP 6 — Building YouTube metadata")
    yt_meta = build_metadata_from_script(
        topic       = topic,
        script      = cleaned,
        category_id = YOUTUBE_CATEGORY,
    )
    meta["youtube_metadata"] = yt_meta
    log.info(f"Title      : {yt_meta['title']}")
    log.info(f"Tags       : {yt_meta['tags'][:8]}…")

    # --- NEW: Write meta.json here, before upload attempt ---
    _write_meta(run_dir, meta)
    # --------------------------------------------------------

    # ── Step 7: YouTube upload ────────────────────────────────────────────────
    video_id = None
    if UPLOAD_TO_YOUTUBE and yt_ready:
        log.info("STEP 7 — Uploading to YouTube")
        for attempt in range(3):
            try:
                publish_at_iso = _get_next_publish_time() # Get the next scheduled time
                video_id = upload_short(
                    video_path         = str(output_path),
                    title              = yt_meta["title"],
                    description        = yt_meta["description"],
                    tags               = yt_meta["tags"],
                    category_id        = YOUTUBE_CATEGORY,
                    privacy            = "private", # Must be private for scheduling
                    notify_subscribers = NOTIFY_SUBSCRIBERS,
                    publish_at         = publish_at_iso, # Pass the scheduled time
                )
                log.info(f"Uploaded: https://www.youtube.com/shorts/{video_id}")
                _append_upload_log(timestamp, topic, video_id)
                break
            except Exception as exc:
                log.error(f"Upload error (attempt {attempt+1}): {exc}")
                if attempt < 2:
                    time.sleep(20)

        if not video_id:
            log.error("Upload failed after 3 attempts. Video retained locally.")
    elif UPLOAD_TO_YOUTUBE and not yt_ready:
        log.info("STEP 7 — Upload skipped (credentials not configured).")
    else:
        log.info("STEP 7 — Upload skipped (UPLOAD_TO_YOUTUBE=False).")

    meta["youtube_video_id"] = video_id
    meta["youtube_url"] = f"https://www.youtube.com/shorts/{video_id}" if video_id else None

    # ── Finalise ──────────────────────────────────────────────────────────────
    # OLD: _write_meta(run_dir, meta) # Moved this up
    _evict_old_runs()

    log.info("=" * 56)
    log.info("Pipeline complete!")
    log.info(f"  Topic  : {topic}")
    log.info(f"  Output : {output_path}")
    if video_id:
        log.info(f"  YouTube: https://www.youtube.com/shorts/{video_id}")
    log.info("=" * 56)

    return meta


# =============================================================================
if __name__ == "__main__":
    try:
        run_pipeline()
    except Exception as exc:
        log.critical(f"Pipeline aborted: {exc}", exc_info=True)
        sys.exit(1)