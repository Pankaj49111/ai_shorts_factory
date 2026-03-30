# AGENTS.md — AI Shorts Factory

A fully-hardened YouTube Shorts factory automation pipeline that generates science/psychology fact videos with narration, b-roll, and captions. Each run produces an isolated output directory with all artifacts.

## Architecture Overview

**Entry Point:** `pipeline_runner.py` → orchestrates a linear pipeline of transformations:

```
Trending Topic → Script (Gemini) → Voice (Edge-TTS) → Keywords → B-Roll (Pexels)
                                                                      ↓
                                                              Captions (Whisper)
                                                                      ↓
                                                              Video Assembly
                                                                      ↓
                                                              YouTube Upload
```

### Key Architectural Decisions

- **Per-run isolation:** Every pipeline execution creates `assets/runs/<YYYYMMDD_HHMMSS>/` with its own narration.mp3, broll/, script.txt, output.mp4, meta.json. Older runs auto-evict (keeps 3 newest).
- **B-roll fallback cascade:** Try Pexels API → cache dir (reuse with synthetic offsets like `::rev::off=5`) → fail gracefully with warning.
- **MoviePy v2 upgrade:** Uses new `moviepy>=2.0` API. Old code using `vfx.AddMarginLeft` is incompatible—replaced with `vfx.Resize()` + `vfx.Crop()`.
- **Whisper transcription:** faster-whisper (CPU-only, int8) transcribes narration for word-sync captions. Three modes: karaoke (active word white), highlight (power words gold), simple (plain white).
- **Environment isolation:** SadTalker (avatar generation) runs in separate conda env (python 3.8) due to PyTorch conflicts.

## Critical Files

| File | Purpose |
|------|---------|
| `pipeline_runner.py` | Main orchestrator—reads config, calls each pipeline stage, handles eviction |
| `pipeline/video_assembler.py` | Composes 1080x1920 portrait video from b-roll + captions (MoviePy v2) |
| `pipeline/caption_generator.py` | Word-sync captions via Whisper + three stylization modes |
| `pipeline/script_generator.py` | Generates HOOK/BODY/OUTRO scripts via Gemini 2.5-flash |
| `pipeline/broll_fetcher.py` | Pexels API integration with per-run isolation |
| `pipeline/trend_fetcher.py` | Google Trends + YouTube trending + Gemini filtering |
| `pipeline/voice_generator.py` | Edge-TTS wrapper for narration synthesis |
| `pipeline/keyword_extractor.py` | Extracts keywords for b-roll search queries |

## Common Workflows & Commands

### Full Pipeline
```powershell
# Set .env with: GEMINI_API_KEY, PEXELS_API_KEY, OPENAI_API_KEY, YouTube credentials
python pipeline_runner.py
```

### Debug Specific Stages
```powershell
# Test TTS voice output
python pipeline/test_tts.py

# Check available US voices
python check_us_voices.py

# Validate voices (tests against test_voices/ audio files)
python test_voices.py
```

### Configuration
Edit `pipeline_runner.py` top section for:
- `TARGET_DURATION = (20, 28)` — Shorts length target
- `CAPTION_MODE = "karaoke"` — karaoke|highlight|simple
- `WHISPER_MODEL = "base"` — tiny|base|small
- `MIN_BROLL_CLIPS = 5` — minimum scene cuts
- `KEEP_RUNS = 3` — eviction policy
- `UPLOAD_TO_YOUTUBE = True/False`

## Project-Specific Patterns

### Video Composition (MoviePy v2)
- Use `.with_effects([vfx.Effect()])` not `.fx(Effect())`
- Use `.with_duration()`, `.with_start()`, `.with_position()` for clip timing
- Always call `.close()` on VideoFileClip after use to avoid memory leaks
- Portrait conversion: centre-crop if wider than 9:16, resize if taller

Example from `video_assembler.py`:
```python
clip = clip.with_effects([vfx.MultiplySpeed(BROLL_SPEED)])
clip = clip.with_effects([vfx.Crop(x1=x1, x2=x1 + new_w)])
clip = clip.with_effects([vfx.Resize((TARGET_W, TARGET_H))])
```

### Caption Styling (TextClip positioning)
Captions use `Y_POSITION = 0.65` (65% down from top). For vertical centering, apply `y_px - wc.size[1] // 2`. **Known issue:** Captions may be partially cut if `Y_POSITION` is too close to bottom or text exceeds frame width—adjust Y_POSITION downward or reduce FONT_SIZE in `caption_generator.py`.

### B-Roll Clip Entry Parsing
Clips can include synthetic directives for reuse:
```
/path/clip.mp4::rev::off=5
```
- `::rev` = reverse playback
- `::off=5` = seek 5 seconds in before trimming
Parsed by `_parse_clip_entry()` in `video_assembler.py`.

### Gemini API (google-genai SDK)
Use new SDK (`google-genai`), NOT deprecated `google-generativeai`. Model: `gemini-2.5-flash` for fast script generation.

### Environment Variables
- `GEMINI_API_KEY` — Google Genai API key
- `PEXELS_API_KEY` — Pexels video API key
- `OPENAI_API_KEY` — Not currently used (placeholder for future audio processing)
- YouTube OAuth files in `credentials/` for upload

### PyTorch / SadTalker Setup
Separate conda environment required to avoid conflicts:
```bash
conda create -n sadtalker python=3.8 -y
conda activate sadtalker
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
conda install ffmpeg -y
cd path/to/SadTalker
pip install -r requirements.txt
```

## Known Constraints & Gotchas

1. **MoviePy v2 breaking changes:** `vfx.AddMarginLeft`, `vfx.speedx()`, `vfx.time_mirror()`, `vfx.volumex()`, `vfx.crop()`, `vfx.resize()` removed. Use `Resize()`, `Crop()`, `MultiplySpeed()`, `TimeMirror()`, `MultiplyVolume()`.
2. **Google Trends flaky:** May be blocked (404/429). Falls back to YouTube trending + Gemini filtering.
3. **Caption clipping:** If captions appear cut off vertically, lower `Y_POSITION` (try 0.55) or reduce `FONT_SIZE` in `caption_generator.py`.
4. **Font fallback:** If custom font not found, auto-searches: Montserrat → DejaVu → Helvetica → Arial. Ensure `assets/fonts/Montserrat-Bold.ttf` exists for best rendering.
5. **Whisper CPU-only:** Uses int8 quantization for speed. Transcription ~5-10s per minute of audio.
6. **B-roll search:** Generated queries via `keyword_extractor.py`. May not match topic perfectly—inspect `assets/logs/pipeline.log` for query details.

## Integration Points

- **Gemini 2.5-flash** ← script generation (HOOK/BODY/OUTRO format)
- **Edge-TTS** ← narration synthesis (female voice default, configurable in `voice_generator.py`)
- **Faster-Whisper** ← transcription for captions
- **Pexels API** ← portrait b-roll video clips
- **YouTube Data API** ← trending topics + upload
- **SadTalker (external conda env)** ← avatar generation (optional, not in main pipeline yet)
- **FFmpeg** ← video encoding (used internally by MoviePy)

## Debugging Checklist

- **Pipeline hangs:** Check for Pexels API key validity; inspect `assets/logs/pipeline.log`
- **No captions:** Ensure `CAPTION_MODE` is set; check Whisper model downloaded (first run ~500MB download)
- **Black bars on b-roll:** May be portrait-conversion crop; check clip aspect ratio. Verify clips are 9:16 or wider.
- **Caption text cut off:** Reduce `FONT_SIZE` or adjust `Y_POSITION` downward
- **Audio sync drift:** Check narration duration vs. b-roll total duration in logs; may need to adjust `target_duration` config
