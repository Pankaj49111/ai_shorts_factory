AI Shorts Factory — Complete Setup & Cloud Deployment Guide
============================================================

════════════════════════════════════════════════════════════
SECTION 1: BUG FIXES APPLIED IN THIS UPDATE
════════════════════════════════════════════════════════════

Bug 1 — Caption crash
Error:  build_caption_clips() got an unexpected keyword argument 'video_width'
Fix:    Changed to video_size=(1080, 1920) tuple — the actual parameter name
File:   video_assembler.py  line ~244

Bug 2 — YouTube retrying a config error 3×
Error:  Wasted 40s retrying FileNotFoundError for missing client_secret.json
Fix:    Added is_youtube_configured() pre-flight check in pipeline_runner.py.
Called ONCE at startup. If creds missing → skip upload immediately with
clear setup instructions. No retries on config errors.
Files:  youtube_uploader.py (new function), pipeline_runner.py (pre-flight)

Bug 3 — Narration 36.89s hard-cut at 28s (script too long)
Error:  Script word limit was 110 words = ~44s audio >> 28s max
Fix:    MAX_SCRIPT_WORDS = 62 (≈25s at JennyNeural's ~2.5 words/sec)
File:   pipeline_runner.py  CONFIG section
NOTE:   You MUST also update your script_generator.py prompt to say:
"Write a script of EXACTLY 50-60 words. No more than 60 words."
The pipeline enforces it but Gemini should target it from the start.

Bug 4 — AddMarginLeft(top=..., bottom=...) wrong signature
Error:  vfx.AddMarginLeft does not accept top/bottom kwargs → crash on
portrait clips that aren't exactly 9:16
Fix:    Replaced with ColorClip background + with_position('center')
File:   video_assembler.py  _fit_to_portrait()

Bug 5 — TimeReverse on clip with audio track
Error:  moviepy v2 TimeReverse can error on clips that still carry audio
Fix:    VideoFileClip now loaded with audio=False (audio stripped on load)
File:   video_assembler.py  _load_and_prepare_clip()

Bug 6 — CompositeAudioClip.subclipped() not supported
Error:  CompositeAudioClip doesn't support subclipped()
Fix:    Use .with_duration(final_dur) instead
File:   video_assembler.py  audio mix section


════════════════════════════════════════════════════════════
SECTION 2: YOUTUBE CREDENTIALS SETUP (LOCAL — DO THIS ONCE)
════════════════════════════════════════════════════════════

Step 1 — Google Cloud Console
a. Go to https://console.cloud.google.com/
b. Create new project → name it "ai-shorts-factory"
c. Left menu → APIs & Services → Enable APIs
d. Search "YouTube Data API v3" → Enable

Step 2 — Create OAuth credentials
a. APIs & Services → Credentials → + Create Credentials → OAuth 2.0 Client ID
b. Application type: Desktop app
c. Name: AI Shorts Factory
d. Create → Download JSON
e. Rename the file to: client_secret.json
f. Move it to:  D:\Python_work\ai_shorts_factory\credentials\client_secret.json

Step 3 — First-time authentication (browser popup, happens once)
cd D:\Python_work\ai_shorts_factory
.venv\Scripts\python.exe pipeline\youtube_uploader.py

A browser window opens. Sign in with your YouTube channel account.
Click Allow. Browser shows "Authentication successful".
File created: credentials\token.json
All future pipeline runs are fully silent.

Step 4 — Verify
.venv\Scripts\python.exe pipeline\youtube_uploader.py test_video.mp4 "Test Title"
Should upload as private and print the YouTube URL.


════════════════════════════════════════════════════════════
SECTION 3: CLOUD AUTOMATION (FREE — GITHUB ACTIONS)
════════════════════════════════════════════════════════════

Why GitHub Actions:
- 2,000 free minutes/month on public repos (or 500 on private)
- Each pipeline run takes ~8-12 minutes → ~600 min/month for 2x/day
- Scheduled cron, no server, no credit card required
- Persistent storage via Actions cache for b-roll pool + seen topics

Step 1 — Prepare your repo
a. Create a new GitHub repo (can be private)
b. Push your entire ai_shorts_factory/ folder to it
c. Add to .gitignore:
credentials/
assets/runs/
assets/broll_cache/
assets/audio/
.env

Step 2 — Encode credentials as base64 (run on your local Windows machine)
Open PowerShell:
[Convert]::ToBase64String([IO.File]::ReadAllBytes("credentials\client_secret.json")) | clip
# Paste into GitHub secret: YOUTUBE_CLIENT_SECRET_B64

    [Convert]::ToBase64String([IO.File]::ReadAllBytes("credentials\token.json")) | clip
    # Paste into GitHub secret: YOUTUBE_TOKEN_B64

Step 3 — Add all GitHub Secrets
Repo → Settings → Secrets and variables → Actions → New repository secret

Secret name                  Value
─────────────────────────────────────────────────────────
GEMINI_API_KEY               your Gemini API key
PEXELS_API_KEY               your Pexels API key
REDDIT_CLIENT_ID             your Reddit app client ID
REDDIT_CLIENT_SECRET         your Reddit app client secret
YOUTUBE_CLIENT_SECRET_B64    base64 of client_secret.json (from Step 2)
YOUTUBE_TOKEN_B64            base64 of token.json (from Step 2)
YOUTUBE_CHANNEL_NICHE        e.g. "science facts"  (optional)

Step 4 — Add the workflow file
Save the file run_pipeline.yml to:
.github/workflows/run_pipeline.yml

Commit and push. GitHub will start running on the schedule automatically.

Step 5 — Monitor
GitHub repo → Actions tab → watch each run live
Download output videos from the "output-NNN" artifact on each run
Download logs from the "logs-NNN" artifact

Step 6 — Token refresh handling
The YouTube OAuth token expires every 7 days but auto-refreshes during use.
If the pipeline runs at least every 7 days (it runs 2x/day), the token stays
valid indefinitely. If it ever expires:
1. Run locally: python pipeline/youtube_uploader.py
2. Re-encode and update the YOUTUBE_TOKEN_B64 secret.


════════════════════════════════════════════════════════════
SECTION 4: FREE TOOL UPGRADES (BETTER THAN WHAT YOU'RE USING)
════════════════════════════════════════════════════════════

Current                        Better Free Alternative
─────────────────────────────────────────────────────────────────────
edge-tts (JennyNeural)      →  edge-tts (en-US-AriaNeural) — sounds warmer,
higher retention in A/B tests on Shorts
OR en-US-GuyNeural for male voice variety

pytrends alone              →  pytrends + Google Trends RSS feed
(more reliable; pytrends gets blocked often)
RSS: https://trends.google.com/trends/trendingsearches/daily/rss?geo=US

Pexels only                 →  Pexels + Pixabay API (also free, different library)
Doubles your b-roll pool for free
https://pixabay.com/api/docs/

faster-whisper base model   →  faster-whisper small model (better caption accuracy)
Still runs ~2x realtime on CPU, 4x on your GTX 1650
Change: WHISPER_MODEL = "small"

No thumbnail                →  Auto-generate with Pillow (already installed)
Grab frame at t=2s, overlay title text, upload via
youtube.thumbnails().set() — massive CTR boost

No chapter markers          →  Already in description as "0:00 — {topic}"
Helps YouTube understand content → better ranking

No end screen / cards       →  Add via YouTube Studio after upload (manual, 2 min)
Or automate via youtube.videos().update() with
endScreens resource — free API call

Reddit API free tier        →  Reddit API limits 100 req/min — sufficient
Add r/todayilearned, r/science, r/worldnews to
trend_fetcher for higher-quality topics than
pure Google Trends


════════════════════════════════════════════════════════════
SECTION 5: MISSING PIPELINE MODULES (YOU NEED THESE)
════════════════════════════════════════════════════════════

Your pipeline imports these but they haven't been shared — make sure these
exist in your pipeline/ folder and work correctly:

pipeline/trend_fetcher.py      get_trending_topic() → str
pipeline/script_generator.py   generate_script(topic) → str
!! UPDATE PROMPT: target 50-60 words !!
pipeline/script_cleaner.py     clean_script(script) → str
pipeline/voice_generator.py    generate_voice(text, path, voice) → None
pipeline/keyword_extractor.py  extract_keywords(script, count) → list[str]
pipeline/caption_generator.py  build_caption_clips(audio_path, video_size,
mode, model_size) → list

The caption_generator signature must be:
def build_caption_clips(
audio_path: str,
video_size: tuple,        # ← (1080, 1920)  NOT video_width/video_height
mode: str = "karaoke",
model_size: str = "base",
) -> list:

If your existing caption_generator uses video_width/video_height, either:
a. Update caption_generator.py to accept video_size and unpack it, OR
b. Update video_assembler.py to pass separate args — but (a) is cleaner.


════════════════════════════════════════════════════════════
SECTION 6: VIRAL OPTIMISATION — WHAT ACTUALLY DRIVES GROWTH
════════════════════════════════════════════════════════════

Things that move the needle on Shorts (ranked by impact):

1. Hook in first 1-2 seconds
   The first sentence of your script IS the hook. It must create a question
   in the viewer's mind. Gemini prompt should start with:
   "Start with a 1-sentence hook that makes people stop scrolling.
   Example: 'The world's oldest message in a bottle was found after 132 years.'
   Then 2-3 short punchy sentences. End with a 1-sentence payoff.
   TOTAL: 50-60 words MAXIMUM."

2. Watch time / completion rate (most important ranking signal)
    - 20-25s videos complete more often than 28s
    - Cut the outro — you already did this ✓
    - Tight cuts every 4-5s keep eyes moving ✓ (you have min_cuts=5)

3. Title format (already in uploader)
    - Questions and "Did You Know" patterns outperform statements
    - Curiosity gap titles: "Nobody Talks About This..."
    - Numbers: "3 Facts That Will..." — but only if you actually have 3 facts

4. Upload consistency (most underrated factor)
    - 2x/day for 60 days = 120 videos. The algo rewards consistency.
    - Time of upload: 9AM and 3PM IST are good for Indian + US audience overlap
    - Never miss a day — gaps reset momentum

5. Caption style
    - Karaoke (active word highlighted) outperforms static captions on Shorts
    - You already have this ✓
    - Font size: captions should occupy bottom 20% of frame
    - Power word flash (gold) draws attention ✓

6. Niche consistency
    - Pick ONE niche and stay in it for 60 days
    - Mixed-niche channels get suppressed by the algo
    - Set YOUTUBE_CHANNEL_NICHE in .env and keep it

7. What NOT to do
    - Don't use trending music (copyright strikes)
    - Don't add intro cards or outros (kills watch time)
    - Don't reuse the same b-roll in consecutive videos — algo detects it
    - Don't post the same topic twice — you have deduplication ✓


════════════════════════════════════════════════════════════
SECTION 7: FOLDER STRUCTURE AFTER FULL SETUP
════════════════════════════════════════════════════════════

ai_shorts_factory/
.github/
workflows/
run_pipeline.yml          ← cloud schedule (NEW)
pipeline/
trend_fetcher.py
script_generator.py         ← UPDATE prompt for 50-60 words
script_cleaner.py
voice_generator.py
keyword_extractor.py
broll_fetcher.py             ← updated (output_dir param)
video_assembler.py           ← updated (all bugs fixed)
caption_generator.py        ← must accept video_size tuple
youtube_uploader.py          ← updated (pre-flight check + metadata)
pipeline_runner.py             ← updated (word limit + creds preflight)
credentials/
client_secret.json           ← from Google Cloud Console (DO NOT COMMIT)
token.json                   ← auto-generated on first auth (DO NOT COMMIT)
SETUP.md                     ← keep setup notes here
assets/
music/
background.mp3             ← add any royalty-free lo-fi track here
runs/                        ← auto-created per run, auto-evicted
broll_cache/                 ← persistent pool, seeded from Pexels runs
logs/
pipeline.log
upload_log.csv
seen_topics.txt
.env                           ← API keys (DO NOT COMMIT)
.gitignore
requirements.txt