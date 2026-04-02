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
    # Formula 1 — The "real reason" curiosity gap
    lambda kw, hook: f"The Real Reason {kw.title()} (Most People Never Know)",
    # Formula 2 — What-happens frame, search-friendly
    lambda kw, hook: f"What Happens When {kw.title()}",
    # Formula 3 — Mistake pattern, highest CTR
    lambda kw, hook: f"The Mistake Everyone Makes With {kw.title()}",
    # Formula 4 — Science/fact authority frame
    lambda kw, hook: f"What Science Says About {kw.title()}",
    # Formula 5 — Direct question, search intent
    lambda kw, hook: f"Why {kw.title()} Affects You More Than You Think",
    # Formula 6 — Nobody pattern
    lambda kw, hook: f"Nobody Talks About What {kw.title()} Does To You",
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
        "the mistake everyone makes with",
    ]
    kw = topic.lower().strip()
    for sp in stop_phrases:
        kw = kw.replace(sp, "").strip()

    # Take first 4 meaningful words
    words = [w for w in kw.split() if len(w) > 2][:4]
    return " ".join(words).strip(" ,.")


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
    idx = int(hashlib.md5(topic.encode()).hexdigest(), 16) % len(_TITLE_FORMULAS)
    raw_title = _TITLE_FORMULAS[idx](kw, hook)

    # Enforce 60 character limit (YouTube shows full title up to ~60 chars)
    if len(raw_title) > 60:
        raw_title = raw_title[:57].rstrip() + "..."

    return raw_title


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
