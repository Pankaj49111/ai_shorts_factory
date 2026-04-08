from faster_whisper import WhisperModel
from moviepy import TextClip, CompositeVideoClip
import moviepy.video.fx as vfx
import os
import re

# ---------------------------------------------------------------------------
# Style config
# ---------------------------------------------------------------------------
FONT_PATH        = "assets/fonts/Montserrat-Bold.ttf"
FONT_SIZE        = 90
Y_POSITION       = 0.7
STROKE_COLOR     = "black"
STROKE_WIDTH     = 5

# --- Original Mode Configs ---
COLOR_ACTIVE     = "white"
COLOR_INACTIVE   = "#AAAAAA"
COLOR_KEYWORD    = "#FFD700"
WORDS_PER_GROUP  = 3
CONFIDENCE_THRESHOLD = 0.65
POWER_WORDS = {
    "never", "always", "secret", "truth", "actually", "insane", "crazy",
    "shocking", "incredible", "impossible", "proven", "scientists", "brain",
    "memory", "discovered", "million", "billion", "warning", "danger",
    "hidden", "real", "fake", "die", "dead", "alive", "strongest", "fastest",
    "smartest", "richest", "ancient", "mystery", "revealed", "fact"
}

# --- Beast Mode Config ---
IMPACT_WORDS = {
    "money", "win", "lose", "crazy", "insane", "free", "fast", "secret", "viral",
    "million", "billion", "never", "always", "truth", "actually", "shocking",
    "incredible", "impossible", "proven", "scientists", "brain", "memory",
    "discovered", "warning", "danger", "hidden", "real", "fake", "die", "dead",
    "alive", "strongest", "fastest", "smartest", "richest", "ancient", "mystery",
    "revealed", "fact", "unbelievable", "amazing", "terrifying", "critical",
    "essential", "vital", "ultimate", "breakthrough", "massive", "tiny", "only",
    "must", "forbidden", "exposed", "transform", "revolutionize", "create",
    "destroy", "profit", "wealth", "debt", "ai", "data", "science", "future",
    "quantum", "mind", "psychology", "behavior", "human", "universe", "planet",
    "energy", "power", "system", "technology", "digital", "virtual", "code",
    "algorithm", "experiment", "discovery", "research", "evidence", "theory",
    "impact", "effect", "cause", "consequence", "solution", "problem", "challenge",
    "opportunity", "risk", "security", "effective", "efficient", "successful",
    "valuable", "important", "significant", "major", "unique", "original",
    "constant", "stable", "secure", "protected", "powerful", "weak", "gain", "loss"
}
IMPACT_COLOR = "yellow"
IMPACT_FONT_SIZE_BUMP = 20

# --- Mode Selection ---
MODE_KARAOKE   = "karaoke"
MODE_HIGHLIGHT = "highlight"
MODE_SIMPLE    = "simple"
MODE_BEAST     = "beast"

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
        audio_path, word_timestamps=True, language="en",
        vad_filter=True, vad_parameters={"min_silence_duration_ms": 300}
    )
    print(f"  Language: {info.language} ({info.language_probability:.0%})")
    words = []
    for segment in segments:
        if not segment.words: continue
        for w in segment.words:
            if not w.word.strip(): continue
            words.append({"text": w.word.strip(), "start": w.start, "end": w.end, "probability": w.probability})
    print(f"  Got {len(words)} words")
    return words

# ---------------------------------------------------------------------------
# Beast Mode Helpers
# ---------------------------------------------------------------------------
def _chunk_by_timing(words, max_gap=0.5, max_words=3):
    chunks = []
    current = []

    for w in words:
        if not current:
            current.append(w)
            continue

        gap = w["start"] - current[-1]["end"]

        if gap > max_gap or len(current) >= max_words:
            chunks.append(current)
            current = [w]
        else:
            current.append(w)

    if current:
        chunks.append(current)

    formatted_chunks = []
    for chunk in chunks:
        text = " ".join(w['text'] for w in chunk)
        formatted_chunks.append({"text": text, "start": chunk[0]['start'], "end": chunk[-1]['end']})
        
    return formatted_chunks

def _is_impact(text):
    text_words = [re.sub(r"\W", "", w.lower()) for w in text.split()]
    return any(w in IMPACT_WORDS for w in text_words)

def _pop_effect(t):
    return 1 + 0.15 if t < 0.1 else 1

def _make_beast_clips(words, font, video_size):
    if not words: return []
    chunks = _chunk_by_timing(words)
    clips = []
    video_w, _ = video_size
    for chunk in chunks:
        # Slight timing tightening
        start = chunk['start'] + 0.02
        end = chunk['end']
        duration = end - start - 0.04
        
        if duration <= 0.05:
            # Fallback if tightening made it too short
            start = chunk['start']
            duration = chunk['end'] - chunk['start']
            if duration <= 0.05:
                continue
            
        impact = _is_impact(chunk['text'])
        txt = chunk['text'].upper() if impact else chunk['text']
        fontsize = FONT_SIZE + IMPACT_FONT_SIZE_BUMP if impact else FONT_SIZE
        color = IMPACT_COLOR if impact else "white"
        
        # Note: MoviePy 2 doesn't have .margin() on TextClip directly, wait for assembly if needed.
        # But we can align it center safely
        clip = TextClip(
            text=txt, font=font, font_size=fontsize, color=color,
            stroke_color=STROKE_COLOR, stroke_width=STROKE_WIDTH, method="label", text_align="center"
        )
        
        if clip.size[0] > video_w - 80:
            scale_factor = (video_w - 80) / clip.size[0]
            new_w = max(1, int(clip.size[0] * scale_factor))
            new_h = max(1, int(clip.size[1] * scale_factor))
            clip = clip.with_effects([vfx.Resize((new_w, new_h))])
            
        final_clip = clip.with_position(("center", Y_POSITION), relative=True).with_start(start).with_duration(duration)
        
        if impact:
            # using lambda t for dynamic scaling in moviepy v2 might be tricky without a proper generator
            # applying simple pop via standard scale if supported, else skipping to avoid breaks
            try:
                 final_clip = final_clip.with_effects([vfx.Resize(lambda t: _pop_effect(t))])
            except Exception:
                 pass
            
        clips.append(final_clip)
    return clips

# ---------------------------------------------------------------------------
# Original Grouping & Clip Builders
# ---------------------------------------------------------------------------
def _group_words(words, n=WORDS_PER_GROUP):
    groups = []
    for i in range(0, len(words), n):
        chunk = words[i:i + n]
        groups.append({"words": chunk, "start": chunk[0]["start"], "end": chunk[-1]["end"]})
    return groups

def _is_power_word(text):
    return text.lower().strip(".,!?\"'") in POWER_WORDS

def _row_composite(word_color_pairs, font, duration, start_time, frame_w=1080, frame_h=1920):
    word_clips, x_offset = [], 0
    for word_text, color in word_color_pairs:
        if not word_text.strip(): continue
        wc = TextClip(font=font, text=word_text + " ", font_size=88, color=color, stroke_color=STROKE_COLOR, stroke_width=4, method="label")
        if wc.size[0] == 0 or wc.size[1] == 0: continue
        word_clips.append((wc, x_offset)); x_offset += wc.size[0]
    if not word_clips: return None
    total_w = x_offset
    scale_factor = (frame_w - 80) / total_w if total_w > frame_w - 80 else 1.0
    start_x = max(40, (frame_w - int(total_w * scale_factor)) // 2)
    y_px = int(0.65 * frame_h)
    positioned = []
    for wc, x_off in word_clips:
        if scale_factor != 1.0:
            new_w = max(1, int(wc.size[0] * scale_factor))
            new_h = max(1, int(wc.size[1] * scale_factor))
            wc = wc.with_effects([vfx.Resize((new_w, new_h))])
            x_off = int(x_off * scale_factor)
        final_y = max(20, min(y_px - wc.size[1] // 2, frame_h - wc.size[1] - 20))
        positioned.append(wc.with_position((start_x + x_off, final_y)).with_duration(duration))
    return CompositeVideoClip(positioned, size=(frame_w, frame_h)).with_duration(duration).with_start(start_time)

def _make_simple_clip(group, font):
    text = " ".join(w["text"] for w in group["words"])
    if not text.strip(): return None
    duration = max(0.05, group["end"] - group["start"])
    wc = TextClip(font=font, text=text, font_size=88, color=COLOR_ACTIVE, stroke_color=STROKE_COLOR, stroke_width=4, method="label", text_align="center")
    if wc.size[0] == 0 or wc.size[1] == 0: return None
    if wc.size[0] > 1080 - 80:
        scale_factor = (1080 - 80) / wc.size[0]
        new_w = max(1, int(wc.size[0] * scale_factor))
        new_h = max(1, int(wc.size[1] * scale_factor))
        wc = wc.with_effects([vfx.Resize((new_w, new_h))])
    return wc.with_duration(duration).with_start(group["start"]).with_position(("center", 0.65), relative=True)

def _make_karaoke_clips(group, font):
    clips, group_words = [], group["words"]
    for active_idx, active_word in enumerate(group_words):
        duration = max(0.05, active_word["end"] - active_word["start"])
        pairs = []
        for i, w in enumerate(group_words):
            color = COLOR_KEYWORD if i == active_idx and _is_power_word(w["text"]) else COLOR_ACTIVE if i == active_idx else ("#666666" if w["probability"] < CONFIDENCE_THRESHOLD else COLOR_INACTIVE)
            pairs.append((w["text"], color))
        clip = _row_composite(pairs, font, duration, active_word["start"])
        if clip: clips.append(clip)
    return clips

def _make_highlight_clips(group, font):
    duration = max(0.05, group["end"] - group["start"])
    if not any(_is_power_word(w["text"]) for w in group["words"]):
        clip = _make_simple_clip(group, font)
        return [clip] if clip else []
    pairs = [(w["text"], COLOR_KEYWORD if _is_power_word(w["text"]) else COLOR_ACTIVE) for w in group["words"]]
    clip = _row_composite(pairs, font, duration, group["start"])
    return [clip] if clip else []

# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def build_caption_clips(audio_path, video_size=(1080, 1920), model_size="base", caption_mode="karaoke"):
    font = _get_font()
    words = transcribe_audio(audio_path, model_size)
    if not words:
        print("  No words — skipping captions")
        return []

    words = [w for w in words if w["probability"] >= 0.4]
    clips = []

    if caption_mode == MODE_BEAST:
        clips = _make_beast_clips(words, font, video_size)
    else:
        groups = _group_words(words, WORDS_PER_GROUP)
        for group in groups:
            if group["end"] - group["start"] <= 0: continue
            if caption_mode == MODE_KARAOKE:
                clips.extend(_make_karaoke_clips(group, font))
            elif caption_mode == MODE_HIGHLIGHT:
                clips.extend(_make_highlight_clips(group, font))
            else: # simple
                clip = _make_simple_clip(group, font)
                if clip: clips.append(clip)

    print(f"  {len(clips)} caption clips built (mode: {caption_mode})")
    return clips