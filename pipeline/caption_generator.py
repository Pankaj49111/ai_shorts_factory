from faster_whisper import WhisperModel
from moviepy import TextClip, CompositeVideoClip, ColorClip
import os

# ---------------------------------------------------------------------------
# Style config
# ---------------------------------------------------------------------------
# Caption positioning: Y_POSITION controls vertical placement
# - 0.0 = top of frame
# - 0.5 = middle of frame
# - 1.0 = bottom of frame
# Default 0.65 works well for most Shorts, but if captions appear cut off:
#   → Try 0.50-0.60 to move captions up
#   → Or reduce FONT_SIZE if text width causes line wrapping
# Note: Bounds checking with 20px safety margin prevents clipping

FONT_PATH        = "assets/fonts/Montserrat-Bold.ttf"
FONT_SIZE        = 88
WORDS_PER_GROUP  = 3
Y_POSITION       = 0.65    # 0=top 1=bottom (moved up from 0.72 for better visibility)

COLOR_ACTIVE     = "white"
COLOR_INACTIVE   = "#AAAAAA"
COLOR_KEYWORD    = "#FFD700"   # gold for power words
STROKE_COLOR     = "black"
STROKE_WIDTH     = 4

CONFIDENCE_THRESHOLD = 0.65

POWER_WORDS = {
    "never", "always", "secret", "truth", "actually", "insane", "crazy",
    "shocking", "incredible", "impossible", "proven", "scientists", "brain",
    "memory", "discovered", "million", "billion", "warning", "danger",
    "hidden", "real", "fake", "die", "dead", "alive", "strongest", "fastest",
    "smartest", "richest", "ancient", "mystery", "revealed", "fact"
}

MODE_KARAOKE   = "karaoke"    # active word white, others gray
MODE_HIGHLIGHT = "highlight"  # power words turn gold
MODE_SIMPLE    = "simple"     # plain white groups

CAPTION_MODE = MODE_KARAOKE   # change this to switch styles


# ---------------------------------------------------------------------------
# Font
# ---------------------------------------------------------------------------

def _get_font():
    if os.path.exists(FONT_PATH):
        return FONT_PATH
    for p in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/Arial.ttf",
    ]:
        if os.path.exists(p):
            return p
    raise FileNotFoundError("No font found. Add .ttf to assets/fonts/")


# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------

def transcribe_audio(audio_path, model_size="base"):
    print(f"  Transcribing with faster-whisper ({model_size})...")
    model = WhisperModel(model_size, device="cpu", compute_type="int8")

    segments, info = model.transcribe(
        audio_path,
        word_timestamps=True,
        language="en",
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 300}
    )

    print(f"  Language: {info.language} ({info.language_probability:.0%})")

    words = []
    for segment in segments:
        if not segment.words:
            continue
        for w in segment.words:
            words.append({
                "text":        w.word.strip(),
                "start":       w.start,
                "end":         w.end,
                "probability": w.probability,
            })

    print(f"  Got {len(words)} words")
    return words


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------

def _group_words(words, n=WORDS_PER_GROUP):
    groups = []
    for i in range(0, len(words), n):
        chunk = words[i:i + n]
        groups.append({
            "words": chunk,
            "start": chunk[0]["start"],
            "end":   chunk[-1]["end"],
        })
    return groups


def _is_power_word(text):
    return text.lower().strip(".,!?\"'") in POWER_WORDS


# ---------------------------------------------------------------------------
# Clip builders
# ---------------------------------------------------------------------------

def _row_composite(word_color_pairs, font, duration, start_time, frame_w=1080, frame_h=1920):
    """Build a horizontal row of colored word clips composited together."""
    word_clips = []
    x_offset   = 0
    for word_text, color in word_color_pairs:
        wc = TextClip(
            font=font, text=word_text + " ",
            font_size=FONT_SIZE,
            color=color,
            stroke_color=STROKE_COLOR,
            stroke_width=STROKE_WIDTH,
            method="label",
        )
        word_clips.append((wc, x_offset))
        x_offset += wc.size[0]

    total_w = x_offset
    start_x = max(0, (frame_w - total_w) // 2)
    y_px    = int(Y_POSITION * frame_h)

    # Position each word clip at the correct x,y pixel coordinates
    # with bounds checking to prevent clipping
    positioned = []
    for wc, x_off in word_clips:
        # Vertically center text, but ensure it stays within frame bounds
        text_half_h = wc.size[1] // 2
        final_y = y_px - text_half_h
        
        # Safety margins: ensure text doesn't exceed top/bottom
        SAFETY_MARGIN = 20  # pixels
        final_y = max(SAFETY_MARGIN, final_y)
        final_y = min(frame_h - wc.size[1] - SAFETY_MARGIN, final_y)
        
        positioned.append(
            wc.with_position((start_x + x_off, final_y))
            .with_duration(duration)
        )

    return (
        CompositeVideoClip(positioned, size=(frame_w, frame_h))
        .with_duration(duration)
        .with_start(start_time)
    )


def _make_simple_clip(group, font):
    text     = " ".join(w["text"] for w in group["words"])
    duration = max(0.05, group["end"] - group["start"])
    return (
        TextClip(
            font=font, text=text,
            font_size=FONT_SIZE,
            color=COLOR_ACTIVE,
            stroke_color=STROKE_COLOR,
            stroke_width=STROKE_WIDTH,
            method="label",
            text_align="center",
        )
        .with_duration(duration)
        .with_start(group["start"])
        .with_position(("center", Y_POSITION), relative=True)
    )


def _make_karaoke_clips(group, font):
    """One sub-clip per word — active word white, rest gray."""
    clips       = []
    group_words = group["words"]

    for active_idx, active_word in enumerate(group_words):
        duration = max(0.05, active_word["end"] - active_word["start"])
        pairs    = []
        for i, w in enumerate(group_words):
            if i == active_idx:
                color = COLOR_KEYWORD if _is_power_word(w["text"]) else COLOR_ACTIVE
            else:
                color = "#666666" if w["probability"] < CONFIDENCE_THRESHOLD else COLOR_INACTIVE
            pairs.append((w["text"], color))

        clips.append(_row_composite(pairs, font, duration, active_word["start"]))

    return clips


def _make_highlight_clips(group, font):
    """One clip per group — power words are gold, rest white."""
    group_words = group["words"]
    duration    = max(0.05, group["end"] - group["start"])

    if not any(_is_power_word(w["text"]) for w in group_words):
        return [_make_simple_clip(group, font)]

    pairs = [
        (w["text"], COLOR_KEYWORD if _is_power_word(w["text"]) else COLOR_ACTIVE)
        for w in group_words
    ]
    return [_row_composite(pairs, font, duration, group["start"])]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def build_caption_clips(audio_path, video_size=(1080, 1920), model_size="base", caption_mode="karaoke"):
    global CAPTION_MODE
    CAPTION_MODE = caption_mode
    font  = _get_font()
    words = transcribe_audio(audio_path, model_size)

    if not words:
        print("  No words — skipping captions")
        return []

    # Drop very low confidence words to avoid garbled captions
    words  = [w for w in words if w["probability"] >= 0.4]
    groups = _group_words(words, WORDS_PER_GROUP)
    clips  = []

    for group in groups:
        if group["end"] - group["start"] <= 0:
            continue
        if CAPTION_MODE == MODE_KARAOKE:
            clips.extend(_make_karaoke_clips(group, font))
        elif CAPTION_MODE == MODE_HIGHLIGHT:
            clips.extend(_make_highlight_clips(group, font))
        else:
            clips.append(_make_simple_clip(group, font))

    print(f"  {len(clips)} caption clips built (mode: {CAPTION_MODE})")
    return clips