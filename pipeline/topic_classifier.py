"""
topic_classifier.py — Zero-API niche cluster classifier (Viral Optimized)
=========================================================
Maps any topic string to one of 4 niche clusters using keyword
matching + scoring. No external API required.

Clusters:
  TECH_SECRETS   → Science & Tech (Category 28)
  BRAIN_SCIENCE  → Education (Category 27)
  BIOLOGY_NATURE → Education (Category 27)
  SCIENCE        → Science & Tech (Category 28)
  VIRAL_FACTS_1  → Entertainment (Category 24)
  VIRAL_FACTS_2  → Entertainment (Category 24)

Usage:
    from pipeline.topic_classifier import classify_topic, CLUSTER_CATEGORY_MAP
    cluster = classify_topic("why your phone tracks you")
    # → "TECH_SECRETS"
"""

from __future__ import annotations
import re

# ── Cluster → YouTube category ID ────────────────────────────────────────────
CLUSTER_CATEGORY_MAP: dict[str, str] = {
    "TECH_SECRETS":  "28",   # Science & Technology
    "BRAIN_SCIENCE": "27",   # Education
    "BIOLOGY_NATURE":"27",   # Education
    "SCIENCE":       "28",   # Science & Technology
    "VIRAL_FACTS_1": "24",   # Entertainment
    "VIRAL_FACTS_2": "24",   # Entertainment
}

# ── Keyword banks per cluster (scored by weight) ──────────────────────────────
# Format: {keyword: weight}   higher weight = stronger signal
_CLUSTER_KEYWORDS: dict[str, dict[str, int]] = {

    "TECH_SECRETS": {
        "phone": 3, "smartphone": 3, "camera": 2, "tracking": 3,
        "privacy": 3, "data": 2, "location": 3, "wifi": 3,
        "bluetooth": 2, "microphone": 2, "hacked": 3, "secret": 2,
        "hidden feature": 3, "algorithm": 2, "battery": 2, "screen": 2,
        "device": 2, "app": 2, "console": 3, "ps4": 3, "ps5": 3,
        "xbox": 2, "overheating": 3, "gadget": 2, "technology": 2,
        "surveillance": 3, "cyber": 2, "tech company": 2, "hardware": 3,
        "glitch": 2, "password": 2, "security": 3, "internet": 1,
    },

    "BRAIN_SCIENCE": {
        "brain": 4, "neuroscience": 4, "memory": 3, "sleep": 3,
        "dream": 2, "neuron": 3, "cortex": 3, "dopamine": 3,
        "serotonin": 3, "hormone": 2, "adrenaline": 2, "cortisol": 3,
        "nervous system": 3, "subconscious": 3, "perception": 2,
        "synapse": 3, "cognitive": 2, "mental fatigue": 3, "focus": 2,
        "attention span": 2, "psychology": 1, "neurological": 4,
        "amygdala": 3, "prefrontal": 3, "brain cells": 3,
    },

    "BIOLOGY_NATURE": {
        "animal": 3, "biology": 3, "organism": 4, "nature": 2,
        "evolution": 3, "species": 3, "wildlife": 3, "predator": 2,
        "prey": 2, "ocean": 2, "deep sea": 3, "creature": 3,
        "insect": 3, "bug": 2, "parasite": 4, "fungus": 3,
        "bacteria": 2, "virus": 2, "dna": 2, "genetic": 2,
        "anatomy": 3, "human body": 3, "bone": 2, "organ": 3,
        "heart": 2, "stomach": 2, "blood": 2, "muscle": 2,
        "survival": 3, "adaptation": 3, "ecosystem": 2,
        "bizarre": 2, "weird": 2, "elephant": 3, "frog": 3, "owl": 3,
    },

    "SCIENCE": {
        "science": 3, "scientific": 3, "physics": 3, "chemistry": 3,
        "universe": 3, "space": 3, "planet": 3, "galaxy": 3,
        "black hole": 3, "quantum": 2, "atom": 3, "moon": 2,
        "sun": 2, "gravity": 3, "light": 2, "speed": 2,
        "energy": 2, "matter": 2, "element": 2, "temperature": 2,
        "magnetic": 2, "electric": 2, "nuclear": 3, "radiation": 2,
        "time": 2, "dimension": 2, "parallel universe": 3,
        "simulation": 3, "mystery": 2, "astronomy": 3, "cosmic": 3,
    },
    
    "VIRAL_FACTS_1": {},
    "VIRAL_FACTS_2": {},
}


def classify_topic(topic: str) -> str:
    """
    Classify a topic string into one of 4 niche clusters.

    Scoring: sum keyword weights for each cluster, return highest scorer.
    Falls back to SCIENCE if no keywords match.

    Args:
        topic: The topic string to classify

    Returns:
        One of: "TECH_SECRETS", "BRAIN_SCIENCE", "BIOLOGY_NATURE", "SCIENCE", "VIRAL_FACTS_1", "VIRAL_FACTS_2"
    """
    topic_lower = topic.lower()
    # Normalise punctuation
    topic_clean = re.sub(r"[^a-z0-9\s\-']", " ", topic_lower)

    scores: dict[str, int] = {cluster: 0 for cluster in _CLUSTER_KEYWORDS}

    for cluster, keywords in _CLUSTER_KEYWORDS.items():
        for keyword, weight in keywords.items():
            if keyword in topic_clean:
                scores[cluster] += weight

    # Ignore wildcard clusters for classification purposes as they don't have keywords
    # Return highest scoring cluster; tie-break alphabetically for determinism
    valid_scores = {k: v for k, v in scores.items() if k not in ["VIRAL_FACTS_1", "VIRAL_FACTS_2"]}
    winner = max(valid_scores, key=lambda c: (valid_scores[c], c))
    if valid_scores[winner] == 0:
        return "SCIENCE"   # safe default with broadest appeal

    return winner


def get_cluster_display_name(cluster: str) -> str:
    """Human-readable cluster label for logging and meta.json."""
    if cluster.startswith("VIRAL_FACTS"):
        return "Bizarre & Viral Facts"
        
    return {
        "TECH_SECRETS":   "Tech Secrets & Hardware",
        "BRAIN_SCIENCE":  "Brain & Neuroscience",
        "BIOLOGY_NATURE": "Biology & Weird Nature",
        "SCIENCE":        "Science & Mysteries",
    }.get(cluster, cluster)


def get_cluster_cta(cluster: str) -> str:
    """Returns a cluster-specific CTA for the end of every script."""
    if cluster.startswith("VIRAL_FACTS"):
        return "Follow for daily bizarre facts that actually exist."
        
    return {
        "TECH_SECRETS":   "Follow for daily tech secrets they don't want you to know.",
        "BRAIN_SCIENCE":  "Follow for daily brain facts that will blow your mind.",
        "BIOLOGY_NATURE": "Follow for daily bizarre biology facts you won't believe.",
        "SCIENCE":        "Follow for daily science facts that actually exist.",
    }.get(cluster, "Follow for more facts every single day.")
