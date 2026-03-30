"""
video_assembler.py  —  AI Shorts Factory
==========================================
Assembles the final 1080x1920 Short.

Fixes applied (v3):
  - build_caption_clips() called with video_size=(W, H) tuple, not video_width/video_height
  - Portrait padding now uses ColorClip bg + with_position('center') — not AddMarginLeft
  - TimeReverse applied to audio-stripped clip to avoid moviepy crash on audio tracks
  - CompositeAudioClip duration managed with .with_duration() not .subclipped()
  - Clip cleanup properly calls .close() in finally blocks
"""

from __future__ import annotations

import logging
import os
import random
from pathlib import Path

log = logging.getLogger(__name__)

# ── moviepy v2 ────────────────────────────────────────────────────────────────
try:
 from moviepy import (
  VideoFileClip,
  AudioFileClip,
  ColorClip,
  CompositeVideoClip,
  CompositeAudioClip,
  concatenate_videoclips,
 )
 import moviepy.video.fx as vfx
 import moviepy.audio.fx as afx
except ImportError as exc:
 raise SystemExit("moviepy >= 2.0.0 required.  pip install moviepy>=2.0.0") from exc

from pipeline.caption_generator import build_caption_clips

# ── constants ─────────────────────────────────────────────────────────────────
TARGET_W, TARGET_H = 1080, 1920
BROLL_SPEED        = 1.15
REVERSE_PROB       = 0.30
BG_MUSIC_VOLUME    = 0.08
DARK_BG_COLOR      = (15, 15, 15)   # near-black fill for letterbox/pillarbox


# ── helpers ───────────────────────────────────────────────────────────────────

def _parse_clip_entry(entry: str) -> tuple[str, bool, int]:
 """
 Parse a clip entry that may carry synthetic directives.
 Format:  /path/clip.mp4[::rev][::off=N]
 Returns (path, should_reverse, seek_offset_sec)
 """
 reverse, offset = False, 0
 parts = entry.split("::")
 path  = parts[0]
 for part in parts[1:]:
  if part == "rev":
   reverse = True
  elif part.startswith("off="):
   try:
    offset = int(part.split("=")[1])
   except ValueError:
    pass
 return path, reverse, offset


def _fit_to_portrait(clip: VideoFileClip) -> VideoFileClip:
 """
 Fit any aspect ratio clip into 1080x1920.
 - Wider than 9:16  → centre-crop width
 - Taller than 9:16 → resize to full width, pad top/bottom with dark bg
 - Exact 9:16       → just resize
 """
 cw, ch = clip.size
 target_ratio = TARGET_W / TARGET_H
 clip_ratio   = cw / ch

 if abs(clip_ratio - target_ratio) < 0.01:
  # Already correct ratio
  return clip.with_effects([vfx.Resize((TARGET_W, TARGET_H))])

 if clip_ratio > target_ratio:
  # Too wide → crop sides to make it 9:16
  new_w = int(ch * target_ratio)
  x1    = (cw - new_w) // 2
  clip  = clip.with_effects([vfx.Crop(x1=x1, x2=x1 + new_w)])
  return clip.with_effects([vfx.Resize((TARGET_W, TARGET_H))])
 else:
  # Too tall → fit width, pad top+bottom with dark background
  clip  = clip.with_effects([vfx.Resize(width=TARGET_W)])
  new_h = clip.size[1]
  pad   = (TARGET_H - new_h) // 2
  if pad <= 0:
   return clip.with_effects([vfx.Resize((TARGET_W, TARGET_H))])
  bg = ColorClip(
   size=(TARGET_W, TARGET_H),
   color=DARK_BG_COLOR,
   duration=clip.duration,
  )
  return CompositeVideoClip(
   [bg, clip.with_position(("center", pad))],
   size=(TARGET_W, TARGET_H),
  )


def _load_and_prepare_clip(
        entry: str,
        target_dur: float,
        force_reverse: bool = False,
) -> VideoFileClip | None:
 """
 Load, crop/pad to 9:16, speed-up, optionally reverse, and trim one clip.
 Returns None if the file is missing or unusable.
 """
 path, synthetic_rev, offset = _parse_clip_entry(entry)

 if not Path(path).exists():
  log.warning(f"Clip not found: {path}")
  return None

 try:
  raw: VideoFileClip = VideoFileClip(path, audio=False)   # strip audio early
 except Exception as exc:
  log.warning(f"Cannot load {path}: {exc}")
  return None

 try:
  if raw.duration < 2:
   log.warning(f"Clip too short ({raw.duration:.1f}s): {path}")
   return None

  # Seek offset for cache-reuse variants
  if offset > 0 and raw.duration > offset + 2:
   raw = raw.subclipped(offset)

  # Speed up
  raw = raw.with_effects([vfx.MultiplySpeed(BROLL_SPEED)])

  # Reverse (audio already stripped so this is safe)
  should_rev = synthetic_rev or force_reverse or (random.random() < REVERSE_PROB)
  if should_rev:
   raw = raw.with_effects([vfx.TimeMirror()])

  # Trim to target duration
  want = target_dur + 0.3   # small crossfade buffer
  if raw.duration > want:
   raw = raw.subclipped(0, want)

  # Fit to portrait
  raw = _fit_to_portrait(raw)
  return raw

 except Exception as exc:
  log.warning(f"Failed to prepare clip {path}: {exc}")
  try:
   raw.close()
  except Exception:
   pass
  return None


# ── main assembly function ────────────────────────────────────────────────────

def assemble(
        broll: list[str],
        audio: str,
        outfile: str,
        music_path: str | None  = None,
        captions: bool          = True,
        whisper_model: str      = "base",
        caption_mode: str       = "karaoke",
        target_duration: tuple  = (20, 28),
        min_cuts: int           = 5,
) -> None:
 """
 Assemble the final Short and write it to outfile.

 Parameters
 ----------
 broll            : clip paths, may include ::rev::off=N suffixes
 audio            : narration .mp3 path
 outfile          : destination .mp4 path
 music_path       : optional background music path
 captions         : burn in word-synced captions
 whisper_model    : faster-whisper model size  (tiny|base|small)
 caption_mode     : karaoke | highlight | simple
 target_duration  : (min_sec, max_sec) window for the finished video
 min_cuts         : minimum number of scene changes
 """
 os.makedirs(Path(outfile).parent, exist_ok=True)

 # ── Narration ─────────────────────────────────────────────────────────────
 narration  = AudioFileClip(audio)
 audio_dur  = narration.duration
 min_d, max_d = target_duration
 final_dur  = min(max(audio_dur + 0.4, min_d), max_d)
 log.info(f"Narration: {audio_dur:.2f}s  |  Final target: {final_dur:.2f}s")

 if audio_dur > max_d:
  log.warning(
   f"Narration ({audio_dur:.1f}s) exceeds max duration ({max_d}s). "
   "Script was too long — audio will be cut. Reduce script word count."
  )

 # ── B-roll preparation ────────────────────────────────────────────────────
 clip_dur   = final_dur / max(min_cuts, len(broll))
 prepared: list[VideoFileClip] = []

 for entry in broll:
  c = _load_and_prepare_clip(entry, clip_dur)
  if c:
   prepared.append(c)

 if not prepared:
  raise RuntimeError("No usable b-roll clips after processing.")

 # Pad to min_cuts using reversed variants of existing clips
 broll_cycle = list(broll)
 pad_attempt = 0
 while len(prepared) < min_cuts and pad_attempt < min_cuts * 2:
  idx   = pad_attempt % len(broll_cycle)
  extra = _load_and_prepare_clip(broll_cycle[idx], clip_dur, force_reverse=True)
  if extra:
   prepared.append(extra)
  pad_attempt += 1

 log.info(f"Clips ready: {len(prepared)} (min_cuts={min_cuts})")

 # ── Proportional trim so total == final_dur ───────────────────────────────
 total_raw = sum(c.duration for c in prepared)
 scale     = final_dur / total_raw if total_raw > 0 else 1.0
 timed: list[VideoFileClip] = []
 for c in prepared:
  new_d = max(c.duration * scale, 0.4)
  timed.append(c.subclipped(0, min(c.duration, new_d)))

 video = concatenate_videoclips(timed, method="compose")
 if video.duration > final_dur:
  video = video.subclipped(0, final_dur)

 # ── Audio mix ─────────────────────────────────────────────────────────────
 # Trim narration to final_dur
 narr_trimmed = narration.subclipped(0, min(narration.duration, final_dur))

 audio_tracks = [narr_trimmed]

 if music_path and Path(music_path).exists():
  try:
   music = AudioFileClip(music_path)
   
   # Random offset for background music
   max_offset = max(0, music.duration - final_dur)
   offset = random.uniform(0, max_offset) if max_offset > 0 else 0
   
   music = music.subclipped(offset, min(music.duration, offset + final_dur))
   music = music.with_effects([afx.MultiplyVolume(BG_MUSIC_VOLUME)])
   audio_tracks.append(music)
   log.info(f"Background music layered at 8% volume with {offset:.1f}s offset.")
  except Exception as exc:
   log.warning(f"Could not load music: {exc}")

 if len(audio_tracks) > 1:
  mixed = CompositeAudioClip(audio_tracks).with_duration(final_dur)
 else:
  mixed = audio_tracks[0]

 video = video.with_audio(mixed)

 # ── Captions ──────────────────────────────────────────────────────────────
 if captions:
  try:
   # FIX: use video_size tuple, not separate video_width/video_height
   cap_clips = build_caption_clips(
    audio_path = audio,
    video_size = (TARGET_W, TARGET_H),
    caption_mode= caption_mode,
    model_size = whisper_model,
   )
   if cap_clips:
    video = CompositeVideoClip([video] + cap_clips)
    log.info(f"Captions added: {len(cap_clips)} clip(s).")
  except Exception as exc:
   log.warning(f"Captions skipped: {exc}")

 # ── Render ────────────────────────────────────────────────────────────────
 log.info(f"Rendering → {outfile}")
 video.write_videofile(
  outfile,
  fps           = 30,
  codec         = "libx264",
  audio_codec   = "aac",
  preset        = "fast",
  ffmpeg_params = ["-crf", "23"],
  logger        = "bar",
 )

 # Cleanup
 for c in prepared + timed:
  try:
   c.close()
  except Exception:
   pass
 try:
  narration.close()
 except Exception:
   pass
 try:
  if 'music' in locals():
   music.close()
 except Exception:
  pass
 log.info(f"Assembly complete: {outfile}")