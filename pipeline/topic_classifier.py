"""
topic_classifier.py — Zero-API niche cluster classifier
=========================================================
Maps any topic string to one of 4 niche clusters using keyword
matching + scoring. No external API required.

Clusters:
  AI_TECH      → Science & Tech (Category 28) · CPM $15-22
  PSYCHOLOGY   → Education (Category 27)      · CPM $2-5
  FINANCE      → Education (Category 27)      · CPM $4-8
  SCIENCE      → Science & Tech (Category 28) · CPM $3-8
  VIRAL_FACTS_1→ Entertainment (Category 24)  · Broad Appeal
  VIRAL_FACTS_2→ Entertainment (Category 24)  · Broad Appeal

Usage:
    from pipeline.topic_classifier import classify_topic, CLUSTER_CATEGORY_MAP
    cluster = classify_topic("why your brain makes bad decisions at night")
    # → "PSYCHOLOGY"
"""

from __future__ import annotations
import re

# ── Cluster → YouTube category ID ────────────────────────────────────────────
CLUSTER_CATEGORY_MAP: dict[str, str] = {
    "AI_TECH":       "28",   # Science & Technology
    "PSYCHOLOGY":    "27",   # Education
    "FINANCE":       "27",   # Education
    "SCIENCE":       "28",   # Science & Technology (Changed from 27 to 28)
    "VIRAL_FACTS_1": "24",   # Entertainment
    "VIRAL_FACTS_2": "24",   # Entertainment
}

# ── Keyword banks per cluster (scored by weight) ──────────────────────────────
# Format: {keyword: weight}   higher weight = stronger signal
_CLUSTER_KEYWORDS: dict[str, dict[str, int]] = {

    "AI_TECH": {
        "ai": 3, "artificial intelligence": 3, "chatgpt": 3, "gpt": 3,
        "machine learning": 3, "deep learning": 3, "neural network": 3,
        "robot": 2, "automation": 2, "algorithm": 2, "tech": 2,
        "software": 2, "app": 1, "smartphone": 2, "computer": 2,
        "quantum": 3, "semiconductor": 2, "chip": 2, "data": 2,
        "cyber": 2, "hack": 2, "code": 2, "programming": 2,
        "openai": 3, "google": 1, "meta ai": 3, "llm": 3,
        "midjourney": 3, "stable diffusion": 3, "prompt": 2,
        "model": 2, "training": 2, "dataset": 2, "silicon": 2,
        "digital": 1, "internet": 1, "social media": 1, "privacy": 2,
        "surveillance": 2, "deepfake": 3, "voice clone": 3,
        "autonomous": 2, "self-driving": 3, "tesla": 2, "drone": 2,
        "spacex": 2, "elon": 1, "tech company": 2, "startup": 1,
        "crypto": 2, "blockchain": 2, "nft": 2, "virtual reality": 2,
        "augmented reality": 2, "metaverse": 2, "wearable": 2,
    },

    "PSYCHOLOGY": {
        "brain": 3, "psychology": 3, "mental": 3, "mind": 3,
        "neuroscience": 3, "behavior": 3, "behaviour": 3, "habit": 2,
        "emotion": 3, "anxiety": 3, "stress": 3, "depression": 3,
        "trauma": 3, "therapy": 2, "cognitive": 3, "memory": 3,
        "sleep": 2, "dream": 2, "decision": 2, "bias": 3,
        "manipulation": 2, "persuasion": 2, "influence": 2,
        "subconscious": 3, "unconscious": 3, "perception": 2,
        "attention": 2, "focus": 2, "procrastination": 3,
        "dopamine": 3, "serotonin": 3, "cortisol": 3, "hormone": 2,
        "addiction": 3, "reward": 2, "motivation": 2, "willpower": 3,
        "social anxiety": 3, "panic": 3, "loneliness": 3, "trust": 2,
        "personality": 2, "introvert": 2, "extrovert": 2,
        "narcissist": 3, "gaslighting": 3, "toxic": 2,
        "relationship": 2, "attachment": 2, "childhood": 2,
        "self-esteem": 2, "confidence": 2, "mindset": 2,
        "happiness": 2, "gratitude": 2, "self-improvement": 2,
    },

    "FINANCE": {
        "money": 3, "finance": 3, "financial": 3, "wealth": 3,
        "invest": 3, "investment": 3, "stock": 3, "market": 2,
        "budget": 3, "saving": 3, "debt": 3, "loan": 3,
        "credit": 3, "bank": 3, "interest rate": 3, "compound": 3,
        "rich": 2, "poor": 2, "income": 3, "salary": 3,
        "tax": 3, "inflation": 3, "economy": 2, "recession": 3,
        "real estate": 3, "property": 2, "rent": 2, "mortgage": 3,
        "retirement": 3, "pension": 3, "401k": 3, "roth ira": 3,
        "dividend": 3, "passive income": 3, "side hustle": 2,
        "entrepreneur": 2, "business": 2, "profit": 2, "revenue": 2,
        "cash flow": 3, "net worth": 3, "asset": 3, "liability": 3,
        "portfolio": 3, "diversify": 3, "hedge fund": 3, "etf": 3,
        "mutual fund": 3, "insurance": 2, "risk": 2, "return": 2,
        "dollar": 2, "currency": 2, "exchange rate": 2, "gold": 2,
        "bitcoin": 2, "wage": 2, "minimum wage": 2, "negotiate": 2,
    },

    "SCIENCE": {
        "science": 3, "scientific": 3, "physics": 3, "chemistry": 3,
        "biology": 3, "universe": 3, "space": 3, "planet": 3,
        "galaxy": 3, "black hole": 3, "quantum": 2, "atom": 3,
        "evolution": 3, "dna": 3, "gene": 3, "cell": 2,
        "virus": 3, "bacteria": 3, "immune": 3, "vaccine": 2,
        "climate": 2, "earth": 2, "ocean": 2, "nature": 2,
        "animal": 2, "species": 2, "extinct": 3, "fossil": 2,
        "dinosaur": 3, "human body": 3, "organ": 2, "heart": 2,
        "experiment": 2, "discovery": 2, "research": 2, "study": 2,
        "lightning": 2, "storm": 2, "earthquake": 2, "volcano": 2,
        "sun": 2, "moon": 2, "gravity": 3, "light": 2, "speed": 2,
        "energy": 2, "matter": 2, "element": 2, "temperature": 2,
        "magnetic": 2, "electric": 2, "nuclear": 3, "radiation": 2,
        "time": 2, "dimension": 2, "parallel universe": 3,
        "consciousness": 3, "simulation": 3, "mystery": 2,
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
        One of: "AI_TECH", "PSYCHOLOGY", "FINANCE", "SCIENCE", "VIRAL_FACTS_1", "VIRAL_FACTS_2"
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
        "AI_TECH":    "AI & Technology",
        "PSYCHOLOGY": "Psychology & Brain",
        "FINANCE":    "Finance & Money",
        "SCIENCE":    "Science & Mysteries",
    }.get(cluster, cluster)


def get_cluster_cta(cluster: str) -> str:
    """Returns a cluster-specific CTA for the end of every script."""
    if cluster.startswith("VIRAL_FACTS"):
        return "Follow for daily bizarre facts that actually exist."
        
    return {
        "AI_TECH":    "Follow for daily AI facts that nobody else covers.",
        "PSYCHOLOGY": "Follow for daily psychology facts that will change how you think.",
        "FINANCE":    "Follow for daily money facts that schools never taught you.",
        "SCIENCE":    "Follow for daily science facts that will blow your mind.",
    }.get(cluster, "Follow for more facts every single day.")
