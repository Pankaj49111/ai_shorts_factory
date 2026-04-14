from faster_whisper import WhisperModel
from moviepy import TextClip, CompositeVideoClip, ColorClip
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

# Cluster definitions for impact words
CLUSTERS = {
    "TECH_SECRETS": {
        "words": {"ai", "data", "technology", "digital", "virtual", "code", "algorithm", "system", "quantum", "future"},
        "bg_color": (0, 150, 255),  # Electric Blue
    },
    "BRAIN_SCIENCE": {
        "words": {"brain", "memory", "mind", "psychology", "behavior"},
        "bg_color": (128, 0, 128),  # Deep Purple
    },
    "BIOLOGY_NATURE": {
        "words": {"human", "universe", "planet", "energy", "power", "alive", "dead", "die"},
        "bg_color": (34, 139, 34),  # Forest Green
    },
    "SCIENCE": {
        "words": {"scientists", "discovery", "research", "evidence", "theory", "experiment", "science", "proven", "discovered"},
        "bg_color": (200, 0, 0),  # Classic Red
    },
    "VIRAL_FACTS": {
        "words": {"money", "win", "lose", "crazy", "insane", "free", "fast", "secret", "viral", "million", "billion", "never", "always", "truth", "actually", "shocking", "incredible", "impossible", "warning", "danger", "hidden", "real", "fake", "strongest", "fastest", "smartest", "richest", "ancient", "mystery", "revealed", "fact", "unbelievable", "amazing", "terrifying", "critical", "essential", "vital", "ultimate", "breakthrough", "massive", "tiny", "only", "must", "forbidden", "exposed", "transform", "revolutionize", "create", "destroy", "profit", "wealth", "debt", "impact", "effect", "cause", "consequence", "solution", "problem", "challenge", "opportunity", "risk", "security", "effective", "efficient", "successful", "valuable", "important", "significant", "major", "unique", "original", "constant", "stable", "secure", "protected", "powerful", "weak", "gain", "loss"},  # Remaining words
        "bg_color": (200, 0, 0),  # Classic Red
    },
}

# The most trending Hormozi style right now:
# - Normal words: White text with light gray background box.
# - Impact words: White text WITH a colored background box based on cluster.
IMPACT_COLOR = "white"    # White for impact words on colored backgrounds
NORMAL_COLOR = "white"    # White for normal words on light gray background

IMPACT_BG_OPACITY = 0.95  # Almost solid box for impact words

NORMAL_BG_COLOR = (200, 200, 200)   # Light gray background for normal words
NORMAL_BG_OPACITY = 0.8             # Semi-transparent for normal words

IMPACT_FONT_SIZE_BUMP = 25

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
    # For a true MrBeast/Hormozi style, we want 1 word per chunk (or maybe 2 if very fast).
    # We'll force 1 word per chunk for maximum pop impact.
    chunks = []
    for w in words:
        chunks.append([w])
    
    formatted_chunks = []
    for chunk in chunks:
        text = " ".join(w['text'] for w in chunk)
        formatted_chunks.append({"text": text, "start": chunk[0]['start'], "end": chunk[-1]['end']})
        
    return formatted_chunks

def _is_impact(text):
    text_words = [re.sub(r"\W", "", w.lower()) for w in text.split()]
    return any(w in IMPACT_WORDS for w in text_words)

def _pop_effect(t, duration):
    # A simple bounce effect: scales up to 1.15 in the first 0.1s, then back to 1.0
    if t < 0.05:
        return 1.0 + (t / 0.05) * 0.15 # scale up to 1.15
    elif t < 0.15:
        return 1.15 - ((t - 0.05) / 0.10) * 0.15 # scale down to 1.0
    return 1.0

def _make_beast_clips(words, font, video_size):
    if not words: return []
    chunks = _chunk_by_timing(words)
    clips = []
    video_w, video_h = video_size
    
    # Calculate vertical position based on ratio
    y_px = int(video_h * Y_POSITION)
    
    for i, chunk in enumerate(chunks):
        start = chunk['start']
        end = chunk['end']
        # Get next start time to prevent overlap
        next_start = chunks[i + 1]['start'] if i + 1 < len(chunks) else start + 10  # Large value for last word
        # Extend duration slightly but cap at next start
        base_duration = max(0.1, end - start + 0.02)
        duration = min(base_duration, next_start - start)

        cluster = _get_cluster(chunk['text'])
        impact = cluster is not None
        txt = chunk['text'].upper()
        fontsize = FONT_SIZE + IMPACT_FONT_SIZE_BUMP if impact else FONT_SIZE
        color = IMPACT_COLOR if impact else NORMAL_COLOR
        if impact:
            bg_rgb = CLUSTERS[cluster]["bg_color"]
            bg_opacity = IMPACT_BG_OPACITY
        else:
            bg_rgb = NORMAL_BG_COLOR
            bg_opacity = NORMAL_BG_OPACITY

        # 1. Create the TextClip
        txt_clip = TextClip(
            text=txt, font=font, font_size=fontsize, color=color,
            stroke_color=STROKE_COLOR, stroke_width=STROKE_WIDTH, method="label", text_align="center"
        )
        
        # Scale if it's too wide
        if txt_clip.size[0] > video_w - 100:
            scale_factor = (video_w - 100) / txt_clip.size[0]
            new_w = max(1, int(txt_clip.size[0] * scale_factor))
            new_h = max(1, int(txt_clip.size[1] * scale_factor))
            txt_clip = txt_clip.with_effects([vfx.Resize((new_w, new_h))])
            
        # 2. Create the Background Block (if opacity > 0)
        padding_x = 40
        padding_y = 20
        bg_w = txt_clip.size[0] + padding_x
        bg_h = txt_clip.size[1] + padding_y
        
        if bg_opacity > 0:
            bg_clip = ColorClip(
                size=(bg_w, bg_h), 
                color=bg_rgb
            ).with_opacity(bg_opacity)
            
            # 3. Composite them together into one container clip
            comp = CompositeVideoClip(
                [
                    bg_clip.with_position("center"),
                    txt_clip.with_position("center")
                ],
                size=(bg_w, bg_h)
            )
        else:
            # No background box for normal words, just the text
            comp = CompositeVideoClip(
                [txt_clip.with_position("center")],
                size=(bg_w, bg_h)
            )
        
        # 4. Position the container on the main video and apply timing
        final_clip = comp.with_position(("center", y_px)).with_start(start).with_duration(duration)
        
        # 5. Apply the "Pop" animation using moviepy v2 resize effect
        # v2 Resize can take a lambda function returning a scale multiplier
        final_clip = _apply_pop_effect(final_clip, duration)

        clips.append(final_clip)

    return clips

def _apply_pop_effect(clip, duration):
    try:
        return clip.with_effects([vfx.Resize(lambda t: _pop_effect(t, duration))])
    except Exception as e:
        print(f"Warning: Could not apply pop effect: {e}")
        return clip

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

def _row_composite(word_color_pairs, font, duration, start_time, frame_w=1080, frame_h=1920, apply_pop=True):
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
    comp = CompositeVideoClip(positioned, size=(frame_w, frame_h)).with_duration(duration).with_start(start_time)
    if apply_pop:
        return _apply_pop_effect(comp, duration)
    else:
        return comp

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
    clip = wc.with_duration(duration).with_start(group["start"]).with_position(("center", 0.65), relative=True)
    return clip

def _make_karaoke_clips(group, font):
    clips, group_words = [], group["words"]
    for active_idx, active_word in enumerate(group_words):
        duration = max(0.05, active_word["end"] - active_word["start"])
        pairs = []
        for i, w in enumerate(group_words):
            color = COLOR_KEYWORD if i == active_idx and _is_power_word(w["text"]) else COLOR_ACTIVE if i == active_idx else ("#666666" if w["probability"] < CONFIDENCE_THRESHOLD else COLOR_INACTIVE)
            pairs.append((w["text"], color))
        clip = _row_composite(pairs, font, duration, active_word["start"], apply_pop=False)
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

def _get_cluster(text):
    word = re.sub(r"\W", "", text.lower())
    for cluster, data in CLUSTERS.items():
        if word in data["words"]:
            return cluster
    return None

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