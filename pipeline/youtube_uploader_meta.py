"""
youtube_uploader_meta.py — SEO-Optimised Metadata Builder v3 (Human/Organic)
=============================================================================
Drop-in replacement for build_metadata_from_script() in youtube_uploader.py.

Improvements over v2:
  ✓ Reverted to the "Human/Organic" description format.
  ✓ Description includes the FULL script text so the YouTube algorithm can 
    read the natural language context (Semantic SEO).
  ✓ Adds a structured timestamp to signal high quality to the algorithm.
  ✓ Replaces "keyword stuffing" lists with natural, relevant hashtags.
  ✓ Maintains the high-CTR viral title formulas.
"""

from __future__ import annotations

import hashlib
import re
from typing import Optional

from pipeline.keyword_extractor import extract_youtube_tags

# ─────────────────────────────────────────────────────────────────────────────
# SEO title formula engine
# ─────────────────────────────────────────────────────────────────────────────

_TITLE_FORMULAS = [
    # Rank 1: 624 avg views
    lambda kw, hook: f"The Truth About {kw.title()}",
    # Rank 2: 585 avg views
    lambda kw, hook: f"Why {kw.title()} Will Shock You",
    # Rank 3: 569 avg views
    lambda kw, hook: f"{kw.title()} — Most People Don't Know This",
    # Rank 4: 465 avg views
    lambda kw, hook: f"The Mistake Everyone Makes With {kw.title()}",
    # Rank 5: backup
    lambda kw, hook: f"Did You Know About {kw.title()}?",
]

# ── BANNED patterns — never use these ─────────────────────────────────────────
_BANNED_PATTERNS = [
    r"Nobody Talks About What .+ Does To You",
    r"What Happens When .+ Does To",
    r"What Science Says About .+ And$",
    r"Why .+ Affects You More Than And$",
    r" Does To You$",
    r"\.\.\.$",   # truncated titles
]

# ── Content safety — titles containing these get regenerated ─────────────────
_UNSAFE_TITLE_WORDS = [
    "penis", "nipple", "nude", "naked", "propellant", "explosive",
    "kill", "murder", "suicide", "rape", "sex ", "porn",
]

# ─────────────────────────────────────────────────────────────────────────────
# Description templates per cluster (Human/Organic Format)
# ─────────────────────────────────────────────────────────────────────────────

_DESCRIPTION_TEMPLATES: dict[str, str] = {
    "AI_TECH": (
        "{hook}\n"
        "Watch to the end — the last fact will surprise you.\n\n"
        "────────────────────────────────\n\n"
        "{script}\n\n"
        "────────────────────────────────\n\n"
        "🔔 Subscribe for daily AI and tech facts you won't believe.\n\n"
        "0:00 — {keyword_title}\n\n"
        "{hashtags}"
    ),
    "PSYCHOLOGY": (
        "{hook}\n"
        "Watch to the end — the last fact will surprise you.\n\n"
        "────────────────────────────────\n\n"
        "{script}\n\n"
        "────────────────────────────────\n\n"
        "🔔 Subscribe for daily psychology facts you won't believe.\n\n"
        "0:00 — {keyword_title}\n\n"
        "{hashtags}"
    ),
    "FINANCE": (
        "{hook}\n"
        "Watch to the end — the last fact will surprise you.\n\n"
        "────────────────────────────────\n\n"
        "{script}\n\n"
        "────────────────────────────────\n\n"
        "🔔 Subscribe for daily finance facts you won't believe.\n\n"
        "0:00 — {keyword_title}\n\n"
        "{hashtags}"
    ),
    "SCIENCE": (
        "{hook}\n"
        "Watch to the end — the last fact will surprise you.\n\n"
        "────────────────────────────────\n\n"
        "{script}\n\n"
        "────────────────────────────────\n\n"
        "🔔 Subscribe for daily science facts you won't believe.\n\n"
        "0:00 — {keyword_title}\n\n"
        "{hashtags}"
    ),
    "VIRAL_FACTS_1": (
        "{hook}\n"
        "Watch to the end — the last fact will surprise you.\n\n"
        "────────────────────────────────\n\n"
        "{script}\n\n"
        "────────────────────────────────\n\n"
        "🔔 Subscribe for daily bizarre facts you won't believe.\n\n"
        "0:00 — {keyword_title}\n\n"
        "{hashtags}"
    ),
    "VIRAL_FACTS_2": (
        "{hook}\n"
        "Watch to the end — the last fact will surprise you.\n\n"
        "────────────────────────────────\n\n"
        "{script}\n\n"
        "────────────────────────────────\n\n"
        "🔔 Subscribe for daily bizarre facts you won't believe.\n\n"
        "0:00 — {keyword_title}\n\n"
        "{hashtags}"
    ),
}

# Core, natural hashtags that apply broadly
_BASE_HASHTAGS = (
    "#Shorts #YouTubeShorts #DidYouKnow #Facts #Viral #LearnOnShorts"
)

# Targeted, natural hashtags
_CLUSTER_HASHTAGS: dict[str, str] = {
    "AI_TECH":       "#Tech #AI #Technology #Innovation #FutureTech",
    "PSYCHOLOGY":    "#Psychology #MentalHealth #BrainFacts #HumanBehavior",
    "FINANCE":       "#Finance #Money #Wealth #Investing #PersonalFinance",
    "SCIENCE":       "#Science #Nature #Universe #Space #Biology",
    "VIRAL_FACTS_1": "#Bizarre #CrazyFacts #MindBlown #Unbelievable",
    "VIRAL_FACTS_2": "#Bizarre #CrazyFacts #MindBlown #Unbelievable",
}


def _extract_keyword(topic: str) -> str:
    """Extract a 2-4 word keyword phrase from a topic string for use in the title."""
    # Remove hook lead-ins
    stop_phrases = [
        "why", "what", "how", "the real reason", "the hidden reason",
        "nobody talks about", "scientists discovered", "what happens when",
        "what happens to your", "most people never know", "stop doing",
        "you have been doing", "what they never teach you about",
        "the mistake everyone makes with", "did you know", "scientists just discovered",
        "nobody ever explains why", "you have been wrong about",
        "science finally has an answer",
    ]
    kw = topic.lower().strip()
    for sp in stop_phrases:
        kw = kw.replace(sp, "").strip()

    # Remove trailing punctuation fragments
    kw = re.sub(r"[?.!,]+$", "", kw).strip()

    # Take first 4 meaningful words
    words = [w for w in kw.split() if len(w) > 2][:4]
    result = " ".join(words).strip(" ,.")
    return result if result else topic[:30]

def _is_title_safe(title: str) -> bool:
    tl = title.lower()
    for word in _UNSAFE_TITLE_WORDS:
        if word in tl:
            return False
    return True

def _is_title_broken(title: str) -> bool:
    """Returns True if the title matches a known broken pattern."""
    for pattern in _BANNED_PATTERNS:
        if re.search(pattern, title, re.IGNORECASE):
            return True
    return False

def _pick_title_formula(topic: str, script: str) -> str:
    """
    Deterministically pick a title formula based on topic hash
    (so re-runs produce the same title for the same topic).
    """
    # Use first line of script as the hook signal
    hook = script.split(".")[0] if script else topic
    kw = _extract_keyword(topic)
    if not kw:
        kw = topic[:30]

    # Deterministic formula selection via topic hash
    topic_hash = int(hashlib.md5(topic.encode()).hexdigest(), 16)
    formula_idx = topic_hash % len(_TITLE_FORMULAS)

    # Try formulas in order starting from the hash-selected one
    for offset in range(len(_TITLE_FORMULAS)):
        idx   = (formula_idx + offset) % len(_TITLE_FORMULAS)
        raw_title = _TITLE_FORMULAS[idx](kw, hook)

        # Enforce 60 character limit (YouTube shows full title up to ~60 chars)
        if len(raw_title) > 60:
            raw_title = raw_title[:57].rstrip() + "..."

        if not _is_title_broken(raw_title) and _is_title_safe(raw_title):
            return raw_title

    # Last resort — simple safe fallback
    return f"You Won't Believe This About {kw.title()}"[:60]


def build_metadata_from_script(
        topic: str,
        script: str,
        category_id: str = "27",
        cluster: str = "SCIENCE",
) -> dict:
    """
    Build a complete YouTube metadata dict from topic + script + cluster.

    Returns:
        {
            "title":       str,   # SEO-optimised, max 60 chars
            "description": str,   # Human/Organic format with full script
            "tags":        list,  # up to 20 tags, cluster-specific
            "category_id": str,   # passed through from caller
        }
    """
    title = _pick_title_formula(topic, script)

    # Use the extract_youtube_tags for the hidden YouTube metadata tags (not in description)
    tags = extract_youtube_tags(script, count=20)

    # Build description components
    # Extract the hook (first sentence) for the top of the description
    hook = script.split(".")[0].strip() + "." if script else topic
    
    # Capitalize the keyword for the timestamp
    kw = _extract_keyword(topic)
    keyword_title = kw.capitalize() if kw else "The surprising truth"

    # Combine hashtags
    cluster_hashtags = _CLUSTER_HASHTAGS.get(cluster, _CLUSTER_HASHTAGS["SCIENCE"])
    all_hashtags = f"{cluster_hashtags} {_BASE_HASHTAGS}".strip()

    # Format the final description
    template = _DESCRIPTION_TEMPLATES.get(cluster, _DESCRIPTION_TEMPLATES["SCIENCE"])
    description = template.format(
        hook=hook,
        script=script,
        keyword_title=keyword_title,
        hashtags=all_hashtags,
    )

    return {
        "title":       title,
        "description": description,
        "tags":        tags,
        "category_id": category_id,
    }
