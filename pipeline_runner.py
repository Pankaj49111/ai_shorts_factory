"""
pipeline_runner.py — AI Shorts Factory (v7.0 — Harvester Architecture)
======================================================================
What changed from v6.0:
  ✓ Integrated the Trend Harvester architecture.
  ✓ The pipeline now triggers `trend_harvester.py` every 40 successful runs.
  ✓ `trend_fetcher.py` is now a simple consumer of pre-vetted topics.

Entry point: python pipeline_runner.py
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import shutil
import sys
import time
import subprocess
from datetime import datetime, timedelta, time as dt_time, date, timezone
from pathlib import Path
from typing import Optional, Tuple
import math

from pipeline.trend_fetcher       import get_trending_topic
from pipeline.script_generator    import generate_script
from pipeline.script_cleaner      import clean_script
from pipeline.voice_generator     import generate_voice
from pipeline.keyword_extractor   import extract_pexels_queries
from pipeline.broll_fetcher       import download_broll
from pipeline.video_assembler     import assemble
from pipeline.topic_classifier    import CLUSTER_CATEGORY_MAP, get_cluster_display_name
from pipeline.youtube_uploader    import upload_short, is_youtube_configured, QuotaExceededError
from pipeline.youtube_uploader_meta import build_metadata_from_script
from dotenv import load_dotenv

load_dotenv()

try:
    import pytz
except ImportError as exc:
    raise SystemExit(
        "The 'pytz' library is required. Install: pip install pytz"
    ) from exc

# Import AudioFileClip for dynamic b-roll calculation
from moviepy import AudioFileClip

# =============================================================================
# CONFIG
# =============================================================================

RUNS_ROOT     = Path("assets/runs")
BROLL_CACHE_DIR = Path("assets/broll_cache")
MUSIC_DIR     = Path("assets/music")
KEEP_RUNS     = 2

TARGET_DURATION = (25, 48)
MIN_SCRIPT_WORDS = 70
MAX_SCRIPT_WORDS = 105

DESIRED_BROLL_CLIP_DURATION = 4.0
BROLL_RETRY_WAIT = 15
BROLL_MAX_RETRY  = 3

WHISPER_MODEL = "base"

CLUSTER_ROTATION_FILE = Path("assets/logs/cluster_rotation.txt")

# =============================================================================
# DYNAMIC TOGGLE LOGIC
# =============================================================================
# Automatically toggle CAPTION_MODE between "karaoke" and "beast" based on 
# whether the current cluster rotation index is even or odd.
# =============================================================================

def _get_cluster_index() -> int:
    if not CLUSTER_ROTATION_FILE.exists():
        return 0
    try:
        return int(CLUSTER_ROTATION_FILE.read_text().strip())
    except (ValueError, FileNotFoundError):
        return 0

_current_idx = _get_cluster_index()
CAPTION_MODE = "beast" if _current_idx % 2 == 0 else "karaoke"
# =============================================================================

POPULAR_VOICES = [
    "en-US-JennyNeural", "en-US-GuyNeural", "en-US-ChristopherNeural",
    "en-CA-ClaraNeural", "en-CA-LiamNeural", "en-AU-NatashaNeural",
    "en-AU-WilliamMultilingualNeural", "en-IE-ConnorNeural", "en-IE-EmilyNeural"
]

UPLOAD_TO_YOUTUBE   = True
YOUTUBE_PRIVACY     = "private"
NOTIFY_SUBSCRIBERS  = False

# ── Niche clusters (Optimized for Viral Performance based on Analytics) ───
TOPIC_CLUSTERS = [
    "BIOLOGY_NATURE", 
    "TECH_SECRETS", 
    "VIRAL_FACTS_1", 
    "BRAIN_SCIENCE",
    "SCIENCE", 
    "VIRAL_FACTS_2"
]

SEEN_TOPICS_FILE  = Path("assets/logs/seen_topics.txt")
MAX_SEEN_TOPICS   = 1000 # Increased capacity
RUN_COUNTER_FILE = Path("assets/logs/successful_runs.txt")
HARVESTER_CONFIG_FILE = Path("assets/config/trend_sources.json")

IST = pytz.timezone("Asia/Kolkata")
LAST_SCHEDULED_FILE  = Path("assets/logs/last_scheduled_time.txt")
INITIAL_SCHEDULE_DATE = date(2026, 4, 1)
SCHEDULE_TIMES_IST = [dt_time(6, 30), dt_time(12, 0), dt_time(20, 0), dt_time(23, 30)]

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
# Harvester & Helpers
# =============================================================================

def _get_run_count() -> int:
    if not RUN_COUNTER_FILE.exists():
        return 0
    try:
        return int(RUN_COUNTER_FILE.read_text().strip())
    except (ValueError, FileNotFoundError):
        return 0

def _increment_run_count():
    count = _get_run_count() + 1
    RUN_COUNTER_FILE.write_text(str(count))
    log.info(f"Successful runs counter incremented to: {count}")

def _trigger_harvester_if_needed():
    run_count = _get_run_count()
    
    try:
        with open(HARVESTER_CONFIG_FILE, "r") as f:
            config = json.load(f)
        refresh_interval = config.get("refresh_interval_runs", 40)
    except (FileNotFoundError, json.JSONDecodeError):
        log.warning("Harvester config not found or invalid. Using default refresh interval of 40.")
        refresh_interval = 40

    if run_count > 0 and run_count % refresh_interval == 0:
        log.info("=" * 60)
        log.info(f"Run count {run_count} reached. Triggering Trend Harvester...")
        log.info("The pipeline will pause while fresh topics are gathered.")
        log.info("=" * 60)
        
        try:
            # Ensure harvester script exists
            harvester_script = "pipeline/trend_harvester.py"
            if not Path(harvester_script).exists():
                raise FileNotFoundError(f"{harvester_script} not found in the project.")

            # Execute the harvester script as a subprocess
            result = subprocess.run(
                [sys.executable, harvester_script],
                capture_output=True,
                text=True,
                check=True, # This will raise CalledProcessError if the script fails
                encoding="utf-8"
            )
            
            # Log harvester output for debugging
            log.info("--- Trend Harvester Output ---")
            for line in result.stdout.splitlines():
                log.info(f"[Harvester] {line}")
            if result.stderr:
                log.warning("--- Trend Harvester Errors ---")
                for line in result.stderr.splitlines():
                    log.warning(f"[Harvester] {line}")
            
            log.info("=" * 60)
            log.info("Trend Harvester finished. Resuming main pipeline.")
            log.info("=" * 60)
            
        except FileNotFoundError as e:
            log.error(f"Harvester trigger failed: {e}")
        except subprocess.CalledProcessError as e:
            log.error("="*60)
            log.error("Trend Harvester script failed to execute!")
            log.error(f"Return Code: {e.returncode}")
            log.error("--- Harvester STDOUT ---")
            log.error(e.stdout)
            log.error("--- Harvester STDERR ---")
            log.error(e.stderr)
            log.error("="*60)
            # We can decide to continue with the old topics or abort
            log.warning("Continuing with potentially stale topics...")
        except Exception as e:
            log.error(f"An unexpected error occurred while running the harvester: {e}")

def _get_next_cluster() -> str:
    idx = _get_cluster_index()
    clusters = list(TOPIC_CLUSTERS)
    cluster = clusters[idx % len(clusters)]
    
    next_idx = (idx + 1) % len(clusters)
    CLUSTER_ROTATION_FILE.write_text(str(next_idx))

    log.info(f"[cluster] Selected cluster: {cluster} ({get_cluster_display_name(cluster)})")
    return cluster

def _ensure_dirs():
    for d in [RUNS_ROOT, BROLL_CACHE_DIR, Path("assets/logs"), Path("credentials"), MUSIC_DIR, Path("assets/config")]:
        d.mkdir(parents=True, exist_ok=True)

def _evict_old_runs():
    runs = sorted([p for p in RUNS_ROOT.iterdir() if p.is_dir()], key=lambda p: p.name, reverse=True)
    for old in runs[KEEP_RUNS:]:
        log.info(f"Evicting old run: {old.name}")
        shutil.rmtree(old, ignore_errors=True)

def _load_seen_topics() -> set[str]:
    if not SEEN_TOPICS_FILE.exists(): return set()
    return {t.lower() for t in SEEN_TOPICS_FILE.read_text(encoding="utf-8").splitlines() if t.strip()}

def _save_seen_topic(topic: str):
    existing = list(_load_seen_topics())
    existing.append(topic.strip())
    unique = list(dict.fromkeys(reversed(existing)))
    final = list(reversed(unique))[-MAX_SEEN_TOPICS:]
    SEEN_TOPICS_FILE.write_text("\n".join(final) + "\n", encoding="utf-8")

def _get_cached_broll() -> list[str]:
    return [str(p) for p in BROLL_CACHE_DIR.glob("*.mp4")]

def _cache_broll_clips(clips: list[str]):
    for src in clips:
        dst = BROLL_CACHE_DIR / Path(src).name
        if not dst.exists(): shutil.copy2(src, dst)

def _build_fallback_clips(needed: int) -> list[str]:
    cached = _get_cached_broll()
    if not cached: raise RuntimeError("Pexels fetch failed AND broll cache is empty.")
    random.shuffle(cached)
    clips = list(cached)
    while len(clips) < needed:
        base, offset = random.choice(cached), random.randint(1, 8)
        clips.append(f"{base}::rev::off={offset}")
    return clips[:needed]

def _write_meta(run_dir: Path, data: dict):
    (run_dir / "meta.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info(f"Meta saved: {run_dir / 'meta.json'}")

def _append_upload_log(timestamp: str, topic: str, video_id: str, cluster: str):
    path = Path("assets/logs/upload_log.csv")
    url = f"https://www.youtube.com/shorts/{video_id}"
    path.open("a", encoding="utf-8").write(f"{timestamp},{topic},{video_id},{url},{cluster}\n")
    log.info(f"Upload logged: {path}")

def _get_next_publish_time(commit: bool = True) -> str:
    current_utc_dt = datetime.now(timezone.utc)
    last_scheduled_utc: Optional[datetime] = None
    if LAST_SCHEDULED_FILE.exists():
        try:
            raw = LAST_SCHEDULED_FILE.read_text(encoding="utf-8").strip()
            if raw: last_scheduled_utc = datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
        except Exception as exc:
            log.warning(f"Could not read last scheduled time: {exc}")

    base_dt_ist = last_scheduled_utc.astimezone(IST) if last_scheduled_utc else IST.localize(datetime.combine(INITIAL_SCHEDULE_DATE, SCHEDULE_TIMES_IST[0]))
    next_publish_ist = base_dt_ist

    current_slot_idx = -1
    for i, slot_time in enumerate(SCHEDULE_TIMES_IST):
        if next_publish_ist.time() == slot_time:
            current_slot_idx = i
            break

    if current_slot_idx != -1:
        next_slot_idx = (current_slot_idx + 1) % len(SCHEDULE_TIMES_IST)
        if next_slot_idx == 0: next_publish_ist += timedelta(days=1)
        next_publish_ist = next_publish_ist.replace(hour=SCHEDULE_TIMES_IST[next_slot_idx].hour, minute=SCHEDULE_TIMES_IST[next_slot_idx].minute, second=0, microsecond=0)
    else:
        found = False
        for slot_time in SCHEDULE_TIMES_IST:
            candidate = next_publish_ist.replace(hour=slot_time.hour, minute=slot_time.minute, second=0, microsecond=0)
            if candidate > next_publish_ist:
                next_publish_ist, found = candidate, True
                break
        if not found:
            next_publish_ist = (next_publish_ist + timedelta(days=1)).replace(hour=SCHEDULE_TIMES_IST[0].hour, minute=SCHEDULE_TIMES_IST[0].minute, second=0, microsecond=0)

    future_buffer = timedelta(minutes=5)
    while next_publish_ist.astimezone(timezone.utc) < (current_utc_dt + future_buffer):
        log.info(f"Slot {next_publish_ist.strftime('%H:%M IST')} is in the past. Advancing...")
        current_slot_idx = -1
        for i, st in enumerate(SCHEDULE_TIMES_IST):
            if next_publish_ist.time() == st:
                current_slot_idx = i
                break
        next_slot_idx = (current_slot_idx + 1) % len(SCHEDULE_TIMES_IST)
        if next_slot_idx == 0: next_publish_ist += timedelta(days=1)
        next_publish_ist = next_publish_ist.replace(hour=SCHEDULE_TIMES_IST[next_slot_idx].hour, minute=SCHEDULE_TIMES_IST[next_slot_idx].minute, second=0, microsecond=0)

    if commit:
        log.info(f"Next publish: {next_publish_ist.strftime('%Y-%m-%d %H:%M IST')} (UTC: {next_publish_ist.astimezone(timezone.utc).isoformat(timespec='seconds')})")
        LAST_SCHEDULED_FILE.write_text(next_publish_ist.astimezone(timezone.utc).isoformat(timespec="seconds"), encoding="utf-8")
    
    return next_publish_ist.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

# =============================================================================
# Main pipeline
# =============================================================================

def run_pipeline(resume_run_timestamp: Optional[str] = None, caption_override: Optional[str] = None):
    _ensure_dirs()
    
    global CAPTION_MODE
    if caption_override:
        CAPTION_MODE = caption_override
    log.info(f"Using Caption Mode: {CAPTION_MODE.upper()}")

    if not resume_run_timestamp:
        _trigger_harvester_if_needed()

    yt_ready = False
    if UPLOAD_TO_YOUTUBE:
        yt_ready = is_youtube_configured()
        if not yt_ready: log.warning("YouTube upload DISABLED — credentials not found.")

    if resume_run_timestamp:
        run_dir = RUNS_ROOT / resume_run_timestamp
        if not run_dir.is_dir():
            raise FileNotFoundError(f"Resume run directory not found: {run_dir}")
        
        timestamp = resume_run_timestamp
        log.info("=" * 60)
        log.info(f"Resuming pipeline run: {timestamp}")
        log.info(f"Run dir              : {run_dir}")
        log.info("=" * 60)

        meta_path = run_dir / "meta.json"
        
        if not meta_path.exists():
            log.warning(f"meta.json not found in {run_dir}. Attempting to reconstruct from script.txt...")
            script_path = run_dir / "script.txt"
            if not script_path.exists():
                raise FileNotFoundError(f"Cannot resume: Neither meta.json nor script.txt found in {run_dir}")
            
            lines = script_path.read_text(encoding="utf-8").splitlines()
            topic = "unknown_topic"
            cluster = "SCIENCE"
            script_lines = []
            
            for line in lines:
                if line.startswith("TOPIC: "):
                    topic = line[7:].strip()
                elif line.startswith("CLUSTER: "):
                    cluster = line[9:].strip()
                elif not line.startswith("TOPIC:") and not line.startswith("CLUSTER:"):
                    script_lines.append(line)
            
            raw_script = "\n".join(script_lines).strip()
            cleaned = clean_script(raw_script)
            output_path = run_dir / "output.mp4"
            youtube_category = CLUSTER_CATEGORY_MAP.get(cluster, "27")
            
            if not output_path.exists():
                raise FileNotFoundError(f"Cannot resume SEO/Upload: output.mp4 not found in {run_dir}")

            meta: dict = {
                "timestamp": timestamp,
                "run_dir": str(run_dir),
                "topic": topic,
                "cluster": cluster,
                "cluster_display_name": get_cluster_display_name(cluster),
                "script": raw_script,
                "cleaned_script": cleaned,
                "output_path": str(output_path)
            }
        else:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            
            topic = meta.get("topic", "unknown_topic")
            cluster = meta.get("cluster", "SCIENCE")
            cleaned = meta.get("cleaned_script", "")
            output_path = Path(meta.get("output_path", run_dir / "output.mp4"))
            
            youtube_category = CLUSTER_CATEGORY_MAP.get(cluster, "27")
            if "youtube_metadata" in meta:
                youtube_category = meta["youtube_metadata"].get("category_id", youtube_category)

        log.info("Skipping topic fetching, script generation, voice generation, b-roll fetching, video assembly.")
        log.info(f"Loaded Topic: {topic!r}")
        log.info(f"Loaded Cluster: {cluster}")
        log.info(f"Loaded Video Path: {output_path}")

    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = RUNS_ROOT / timestamp
        run_dir.mkdir(parents=True, exist_ok=True)
        broll_dir = run_dir / "broll"
        broll_dir.mkdir(exist_ok=True)

        log.info("=" * 60)
        log.info(f"Pipeline run : {timestamp}")
        log.info(f"Run dir      : {run_dir}")
        log.info("=" * 60)

        meta: dict = {"timestamp": timestamp, "run_dir": str(run_dir)}

        cluster = _get_next_cluster()
        meta["cluster"] = cluster
        meta["cluster_display_name"] = get_cluster_display_name(cluster)
        youtube_category = CLUSTER_CATEGORY_MAP.get(cluster, "27")
        log.info(f"Cluster: {cluster} ({get_cluster_display_name(cluster)}) → YouTube category {youtube_category}")

        log.info("STEP 1 — Fetching trending topic")
        seen = _load_seen_topics()
        topic = get_trending_topic(seen, cluster=cluster)
        log.info(f"Topic: {topic!r}")
        meta["topic"] = topic
        _save_seen_topic(topic)

        log.info(f"STEP 2 — Generating script (target: {MIN_SCRIPT_WORDS}–{MAX_SCRIPT_WORDS} words)")
        script = None
        for attempt in range(4):
            try:
                candidate = generate_script(topic, cluster=cluster)
                word_count = len(candidate.split())
                if MIN_SCRIPT_WORDS <= word_count <= MAX_SCRIPT_WORDS + 5:
                    script = candidate
                    log.info(f"Script accepted: {word_count} words")
                    break
                log.warning(f"Script word count {word_count} outside target — retrying ({attempt+1}/4)")
            except Exception as exc:
                log.error(f"script_generator error ({attempt+1}): {exc}")
                time.sleep(6)
        if not script: raise RuntimeError("Script generation failed after 4 attempts.")
        (run_dir / "script.txt").write_text(f"TOPIC: {topic}\nCLUSTER: {cluster}\n\n{script}", encoding="utf-8")
        meta["script"] = script

        log.info("STEP 3 — Generating voice")
        cleaned = clean_script(script)
        meta["cleaned_script"] = cleaned
        selected_voice = random.choice(POPULAR_VOICES)
        log.info(f"Selected voice for this run: {selected_voice}")
        meta["voice"] = selected_voice
        audio_path = run_dir / "narration.mp3"
        for attempt in range(3):
            try:
                generate_voice(cleaned, str(audio_path), selected_voice)
                if audio_path.stat().st_size < 5_000: raise ValueError("Audio suspiciously small")
                log.info(f"Audio: {audio_path.stat().st_size:,} bytes")
                break
            except Exception as exc:
                log.error(f"voice_generator error ({attempt+1}): {exc}")
                time.sleep(5)
        else:
            raise RuntimeError("Voice generation failed after 3 attempts.")

        with AudioFileClip(str(audio_path)) as narration_clip:
            audio_dur = narration_clip.duration
        min_d, max_d = TARGET_DURATION
        final_video_duration = min(max(audio_dur + 0.4, min_d), max_d)
        broll_queries_for_run = min_broll_clips_for_run = max(3, math.ceil(final_video_duration / DESIRED_BROLL_CLIP_DURATION))
        log.info(f"Dynamic B-roll: Final video duration {final_video_duration:.2f}s -> {min_broll_clips_for_run} clips")

        log.info("STEP 4a — Extracting Pexels keywords")
        queries: list[str] = []
        for attempt in range(3):
            try:
                queries = extract_pexels_queries(script, count=broll_queries_for_run)
                if queries: break
            except Exception as exc:
                log.error(f"keyword_extractor error ({attempt+1}): {exc}")
                time.sleep(5)
        if not queries:
            log.warning("Keyword extraction failed — falling back to topic words.")
            queries = [w.strip(".,!?") for w in topic.split() if len(w) > 3][:broll_queries_for_run]
        log.info(f"B-roll queries: {queries}")
        meta["broll_queries"] = queries

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
                log.warning(f"Only {len(result)} clips returned ({attempt+1}/{BROLL_MAX_RETRY})")
            except Exception as exc:
                log.warning(f"Pexels error ({attempt+1}): {exc}")
                if attempt < BROLL_MAX_RETRY - 1: time.sleep(BROLL_RETRY_WAIT)
        
        broll = list(fresh_clips)
        if len(broll) < min_broll_clips_for_run:
            needed = min_broll_clips_for_run - len(broll)
            log.warning(f"Only {len(broll)}/{min_broll_clips_for_run} clips — pulling {needed} from cache.")
            broll += _build_fallback_clips(needed)
        log.info(f"Final clip list: {len(broll)} clips")
        meta["broll_clips"] = broll

        log.info("STEP 5 — Assembling video")
        output_path = run_dir / "output.mp4"
        music_arg = None
        if MUSIC_DIR and MUSIC_DIR.is_dir():
            music_files = [p for p in MUSIC_DIR.glob("*.mp3") if p.is_file()]
            if music_files:
                music_arg = str(random.choice(music_files))
                log.info(f"Background music: {Path(music_arg).name}")
            else:
                log.warning(f"No .mp3 files in {MUSIC_DIR} — skipping background music.")

        for attempt in range(2):
            try:
                assemble(broll=broll, audio=str(audio_path), outfile=str(output_path), music_path=music_arg, captions=True, whisper_model=WHISPER_MODEL, caption_mode=CAPTION_MODE, target_duration=TARGET_DURATION, min_cuts=min_broll_clips_for_run)
                if not output_path.exists() or output_path.stat().st_size < 50_000: raise ValueError("Output video too small.")
                log.info(f"Video: {output_path.stat().st_size / 1_048_576:.1f} MB → {output_path}")
                break
            except Exception as exc:
                log.error(f"video_assembler error ({attempt+1}): {exc}")
                if attempt == 1: raise RuntimeError(f"Video assembly failed: {exc}") from exc
                time.sleep(6)
        meta["output_path"] = str(output_path)

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 6 & 7 (Executes for both normal runs and resumed runs)
    # ─────────────────────────────────────────────────────────────────────────

    log.info("STEP 6 — Building SEO metadata")
    yt_meta = build_metadata_from_script(topic=topic, script=cleaned, category_id=youtube_category, cluster=cluster)
    meta["youtube_metadata"] = yt_meta
    log.info(f"Title : {yt_meta['title']}")
    log.info(f"Tags  : {yt_meta['tags'][:6]}…")
    _write_meta(run_dir, meta)

    video_id = None
    if UPLOAD_TO_YOUTUBE and yt_ready:
        log.info("STEP 7 — Uploading to YouTube")
        for attempt in range(3):
            try:
                publish_at_iso = _get_next_publish_time(commit=False)
                video_id = upload_short(video_path=str(output_path), title=yt_meta["title"], description=yt_meta["description"], tags=yt_meta["tags"], category_id=youtube_category, privacy="private", notify_subscribers=NOTIFY_SUBSCRIBERS, publish_at=publish_at_iso)
                
                _get_next_publish_time(commit=True)

                log.info(f"Uploaded: https://www.youtube.com/shorts/{video_id}")
                _append_upload_log(timestamp, topic, video_id, cluster)
                break
            except QuotaExceededError as q_err:
                log.warning(f"⚠️ {q_err}")
                log.warning("The video was created successfully but could not be uploaded today.")
                log.warning(f"Use `python retry_upload.py {run_dir}` tomorrow.")
                break 
            except Exception as exc:
                log.error(f"Upload error ({attempt+1}): {exc}")
                if attempt < 2: time.sleep(20)
        if not video_id: log.error("Upload failed. Video retained locally.")
    elif UPLOAD_TO_YOUTUBE and not yt_ready:
        log.info("STEP 7 — Skipped (YouTube credentials not configured).")
    else:
        log.info("STEP 7 — Skipped (UPLOAD_TO_YOUTUBE=False).")

    meta["youtube_video_id"] = video_id
    meta["youtube_url"] = f"https://www.youtube.com/shorts/{video_id}" if video_id else None
    _write_meta(run_dir, meta) 
    
    if not resume_run_timestamp:
        _increment_run_count()

    _evict_old_runs()

    log.info("=" * 60)
    log.info("Pipeline complete!")
    log.info(f"  Cluster : {cluster} ({get_cluster_display_name(cluster)})")
    log.info(f"  Topic   : {topic}")
    log.info(f"  Output  : {output_path}")
    if video_id: log.info(f"  YouTube : https://www.youtube.com/shorts/{video_id}")
    log.info("=" * 60)

    return meta

# =============================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Shorts Factory Pipeline Runner")
    parser.add_argument("--resume-run", type=str,
                        help="Timestamp of a previous run to resume (e.g., 20231027_123456)")
    # Optional arguments to configure pipeline execution flags
    parser.add_argument("--caption-mode", type=str, choices=["karaoke", "beast"],
                        help="Override the configured caption mode")
    args = parser.parse_args()

    try:
        run_pipeline(resume_run_timestamp=args.resume_run, caption_override=args.caption_mode)
    except Exception as exc:
        log.critical(f"Pipeline aborted: {exc}", exc_info=True)
        sys.exit(1)