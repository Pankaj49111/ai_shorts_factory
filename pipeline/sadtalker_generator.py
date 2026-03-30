import subprocess
import os
import glob
import shutil
from moviepy import VideoFileClip, AudioFileClip
from faster_whisper import WhisperModel

# --- Config: update this path to where you cloned SadTalker ---
SADTALKER_PATH  = r"D:\Python_work\AI_tools\SadTalker"
CONDA_ENV_NAME  = "sadtalker"
RESULT_DIR      = "assets/avatar/sadtalker_out"

INTRO_DURATION  = 2.5   # must match video_assembler.py INTRO_DURATION
OUTRO_DURATION  = 2.5   # must match video_assembler.py OUTRO_DURATION


def _slice_audio_wav(audio_path, start, duration, suffix):
    """
    Cut a short WAV segment from the full audio using ffmpeg.
    Returns path to the sliced WAV file.
    """
    out_path = audio_path.replace(".wav", f"_{suffix}.wav").replace(".mp3", f"_{suffix}.wav")
    subprocess.run([
        "ffmpeg", "-y",
        "-i",    audio_path,
        "-ss",   str(start),
        "-t",    str(duration),
        "-ar",   "16000",
        "-ac",   "1",
        out_path
    ], check=True, capture_output=True)
    return out_path


def _mp3_to_wav(mp3_path):
    """Convert full MP3 to WAV for ffmpeg slicing."""
    wav_path = mp3_path.replace(".mp3", "_sadtalker.wav")
    subprocess.run([
        "ffmpeg", "-y",
        "-i",  mp3_path,
        "-ar", "16000",
        "-ac", "1",
        wav_path
    ], check=True, capture_output=True)
    return wav_path


def _find_latest_output(result_dir):
    """Find the most recently created mp4 in result_dir."""
    pattern = os.path.join(result_dir, "**", "*.mp4")
    files   = glob.glob(pattern, recursive=True)
    if not files:
        return None
    return max(files, key=os.path.getctime)


def _run_sadtalker(image_path, audio_path, result_dir, label=""):
    """
    Run one SadTalker inference job.
    Returns path to generated mp4 or None on failure.
    """
    cmd = [
        "conda", "run", "-n", CONDA_ENV_NAME, "--no-capture-output",
        "python", os.path.join(SADTALKER_PATH, "inference.py"),
        "--driven_audio",  audio_path,
        "--source_image",  image_path,
        "--result_dir",    result_dir,
        "--still",
        "--preprocess",    "full",
        "--enhancer",      "gfpgan",
        "--size",          "512",
    ]

    print(f"  Running SadTalker [{label}]...")
    try:
        subprocess.run(cmd, cwd=SADTALKER_PATH, check=True)
    except subprocess.CalledProcessError as e:
        print(f"  SadTalker [{label}] failed: {e}")
        return None

    result = _find_latest_output(result_dir)
    if not result:
        print(f"  No output found for [{label}]")
    return result


def _find_sentence_boundary(audio_path, target, mode="intro", tolerance=1.5):
    """
    Use Whisper to find the nearest sentence-end boundary to `target` seconds.

    mode="intro": find the last word-end BEFORE (target + tolerance)
                  so the avatar finishes a complete sentence
    mode="outro": find the first word-start AFTER (target - tolerance)
                  so the avatar begins on a fresh sentence

    Falls back to the raw target time if Whisper finds nothing nearby.
    """
    try:
        model    = WhisperModel("tiny", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(audio_path, word_timestamps=True, language="en")

        word_ends   = []  # (end_time, word)
        word_starts = []  # (start_time, word)

        for seg in segments:
            if not seg.words:
                continue
            for w in seg.words:
                word_ends.append((w.end, w.word.strip()))
                word_starts.append((w.start, w.word.strip()))

        if mode == "intro":
            # Find last sentence-ending word before target + tolerance
            # Sentence endings: words ending with . ! ?
            candidates = [
                t for t, w in word_ends
                if t <= target + tolerance and any(w.endswith(p) for p in [".", "!", "?"])
            ]
            if candidates:
                best = max(candidates)  # latest complete sentence before cutoff
                print(f"  Intro boundary: '{dict(word_ends)[best]}' at {best:.2f}s (target was {target}s)")
                return best
            # Fallback: nearest word end before target
            candidates = [t for t, w in word_ends if t <= target + tolerance]
            return max(candidates) if candidates else target

        else:  # outro
            # Find first sentence-starting word after target - tolerance
            candidates = [
                t for t, w in word_starts
                if t >= target - tolerance
            ]
            if candidates:
                best = min(candidates)
                print(f"  Outro boundary: '{dict(word_starts)[best]}' at {best:.2f}s (target was {target}s)")
                return best
            return target

    except Exception as e:
        print(f"  Boundary detection failed ({e}), using raw target")
        return target



def generate_talking_avatar(image_path, audio_path, output_path):
    """
    Generate intro + outro talking avatar clips efficiently.

    Instead of rendering the full 35s audio (slow), we:
      1. Slice first INTRO_DURATION seconds of audio  → render intro clip
      2. Slice last  OUTRO_DURATION seconds of audio  → render outro clip

    Returns dict: { "intro": path, "outro": path }
    or None if both fail.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    os.makedirs(RESULT_DIR, exist_ok=True)

    # Step 1: Convert MP3 → WAV
    if audio_path.endswith(".mp3"):
        print("  Converting MP3 to WAV...")
        full_wav = _mp3_to_wav(audio_path)
    else:
        full_wav = audio_path

    # Get total audio duration
    clip      = AudioFileClip(audio_path)
    total_dur = clip.duration
    clip.close()

    # Step 2: Find natural sentence boundaries using Whisper
    # then slice at the nearest complete sentence to INTRO/OUTRO_DURATION
    full_wav_abs   = os.path.abspath(full_wav)
    image_path_abs = os.path.abspath(image_path)

    intro_end   = _find_sentence_boundary(full_wav, target=INTRO_DURATION, mode="intro")
    outro_start = _find_sentence_boundary(full_wav, target=total_dur - OUTRO_DURATION, mode="outro")

    intro_wav = os.path.abspath(_slice_audio_wav(full_wav, 0, intro_end, "intro"))
    outro_wav = os.path.abspath(_slice_audio_wav(full_wav, outro_start, total_dur - outro_start, "outro"))

    print(f"  Intro: 0s -> {intro_end:.2f}s | Outro: {outro_start:.2f}s -> {total_dur:.2f}s")

    # Step 3: Run two fast SadTalker jobs
    intro_result_dir = os.path.abspath(os.path.join(RESULT_DIR, "intro"))
    outro_result_dir = os.path.abspath(os.path.join(RESULT_DIR, "outro"))
    os.makedirs(intro_result_dir, exist_ok=True)
    os.makedirs(outro_result_dir, exist_ok=True)

    intro_mp4 = _run_sadtalker(image_path_abs, intro_wav, intro_result_dir, "intro")
    outro_mp4 = _run_sadtalker(image_path_abs, outro_wav, outro_result_dir, "outro")

    if not intro_mp4 and not outro_mp4:
        print("  Both SadTalker jobs failed")
        return None

    # Step 4: Copy results to expected output paths
    intro_out = output_path.replace(".mp4", "_intro.mp4")
    outro_out = output_path.replace(".mp4", "_outro.mp4")

    if intro_mp4:
        shutil.copy2(intro_mp4, intro_out)
        print(f"  Intro avatar saved: {intro_out}")
    else:
        intro_out = None

    if outro_mp4:
        shutil.copy2(outro_mp4, outro_out)
        print(f"  Outro avatar saved: {outro_out}")
    else:
        outro_out = None

    return {"intro": intro_out, "outro": outro_out}