"""
trend_fetcher.py — Cluster-aware Trending Topic Fetcher v3 (with Wildcards)
===========================================================================
Strategy:
  - If cluster is a strict niche (AI, PSYCH, etc.):
    1. Try pytrends (Google Trends) filtered by cluster keywords.
    2. Fall back to a curated 50-topic bank for that cluster.
  - If cluster is a WILDCARD (VIRAL_FACTS_1 or VIRAL_FACTS_2):
    1. Scrape top posts from viral, fact-based subreddits (the old v4 logic).
    2. Filter results with Gemini for maximum viral potential.
  - Guarantees a fresh, high-potential topic for every run.

Usage:
    from pipeline.trend_fetcher import get_trending_topic
    topic = get_trending_topic(seen_topics, cluster="VIRAL_FACTS_1")
"""

from __future__ import annotations

import logging
import random
import re
import time
import os
import requests
from typing import Optional, Set, List

from dotenv import load_dotenv
from google import genai

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

log = logging.getLogger("pipeline.trend_fetcher")

# ─────────────────────────────────────────────────────────────────────────────
# Curated fallback topic banks for STRICT niches
# ─────────────────────────────────────────────────────────────────────────────
_TOPIC_BANKS: dict[str, list[str]] = {
    "AI_TECH": [
        "how AI is secretly reading your emotions right now",
        "the AI tool that replaced 40 hours of work in 4 minutes",
        "why ChatGPT deliberately gives you incomplete answers",
        "what quantum computing will do to every password on earth",
        "the AI running inside your phone that you never notice",
        "why open source AI terrifies the biggest tech companies",
        "the AI that predicted a patient's cancer before any doctor",
        "why your camera uses artificial intelligence 200 times per photo",
        "what AI learned from watching one billion hours of video",
        "the hidden algorithm that decides what you buy next",
        "why self-driving cars can see in complete darkness",
        "how AI generated an entire scientific paper in 11 seconds",
        "the real reason tech companies want all your personal data",
        "why deepfake voices are now impossible to detect",
        "what AI art is doing to professional designers worldwide",
        "the AI model that writes code better than most developers",
        "why every major bank now uses AI to watch your spending",
        "how AI spots lies in text messages better than humans",
        "the reason AI makes the same mistakes children make",
        "what happens when AI controls critical infrastructure",
        "why AI search is replacing Google faster than anyone expected",
        "the AI that gave a blind person their sight back",
        "how robots learned to walk without anyone programming them",
        "why AI tutors are outperforming human teachers in tests",
        "the dark side of AI that tech companies hide from you",
        "what AI thinks is the most dangerous job in the world",
        "how an AI solved a 50-year-old biology problem in one day",
        "why social media algorithms are designed to make you angry",
        "the AI chip that uses less power than a human brain",
        "what every smartphone will be able to do in just 5 years",
        "how AI is changing what it means to be a programmer",
        "why AI voice clones are being used in phone scams right now",
        "the AI model trained entirely on human dreams",
        "what happens when AI writes the laws that govern AI",
        "why AI music is being removed from streaming platforms",
        "how scientists used AI to translate a 2000-year-old scroll",
        "the reason AI consistently beats humans at strategy games",
        "why AI-generated images contain invisible hidden messages",
        "what AI surveillance cameras track in public spaces every day",
        "how an AI startup beat Google at its own core business",
        "the truth about what AI is doing to jobs globally right now",
        "why your AI assistant is trained to avoid certain questions",
        "how AI detects emotions from the way you type",
        "the AI model that predicted major stock crashes 48 hours early",
        "why the next AI breakthrough will come from biology not math",
        "how AI is being used to discover new elements on the periodic table",
        "the hidden cost of every message you send to an AI chatbot",
        "why AI systems develop unexpected behaviours nobody programmed",
        "what AI thinks about its own consciousness",
        "the AI that learned to play every video game ever made",
    ],
    "PSYCHOLOGY": [
        "why your brain makes its worst decisions after 9pm",
        "the 3-second rule that stops anxiety before it spirals",
        "what silence does to your nervous system",
        "why you remember painful memories more clearly than happy ones",
        "the psychological trick that builds instant trust with strangers",
        "why your brain confuses hunger with loneliness",
        "what happens in your mind when someone gives you the silent treatment",
        "the real reason smart people make the worst decisions under pressure",
        "why your dreams get more intense during stressful periods",
        "what your brain is doing in the first 7 seconds you meet someone",
        "the psychological reason you procrastinate on important tasks",
        "why the human brain is physically unable to multitask",
        "what happens to your dopamine when you scroll social media",
        "the mental trick that elite athletes use to stay calm under pressure",
        "why being rejected activates the same pain centres as physical injury",
        "what chronic overthinking actually does to your brain structure",
        "the reason you feel exhausted after doing nothing all day",
        "why humans are the only animals that feel embarrassment",
        "what your body language reveals about you before you speak",
        "the cognitive bias that makes people defend wrong decisions",
        "why music gives you goosebumps and what it says about your brain",
        "what happens to your brain chemistry when you fall in love",
        "the psychological effect of being watched even by a photograph",
        "why your brain creates false memories without you knowing",
        "what the colour of a room does to your mood and productivity",
        "the reason some people feel no fear while others panic easily",
        "why your brain treats social exclusion as a survival threat",
        "what gaslighting does to your brain over time",
        "the psychological reason kind people attract manipulative partners",
        "why humans are wired to follow authority even when it is wrong",
        "what happens to your attention span after just one interrupted task",
        "the reason you feel worse after venting about your problems",
        "why your personality changes depending on who you are with",
        "what narcissism actually looks like in everyday behaviour",
        "the psychological effect of walking into a room and forgetting why",
        "why your brain physically changes every time you learn something new",
        "what loneliness does to your immune system within weeks",
        "the reason people stay in bad situations even when they can leave",
        "why you can smell danger before your brain consciously registers it",
        "what happens to your brain after just one week without exercise",
        "the psychological reason breakups hurt more than other kinds of loss",
        "why humans instinctively trust symmetrical faces more",
        "what your handwriting reveals about your emotional state",
        "the reason childhood experiences shape adult decision-making forever",
        "why the most confident people in the room are often the least competent",
        "what happens to your brain when you hold a grudge for years",
        "the psychological trick that makes people more honest with you",
        "why humans find it harder to lie in person than in text",
        "what your brain does with information you consciously forget",
        "the reason anger feels satisfying even when it makes things worse",
    ],
    "FINANCE": [
        "why your savings account is quietly making you poorer every year",
        "the salary negotiation trick that most people never use",
        "what banks are not telling you about compound interest",
        "why wealthy people almost never buy things on sale",
        "the money mistake that 80 percent of people make before age 30",
        "what inflation has already done to your savings without you noticing",
        "why paying minimum credit card payments is designed to keep you in debt",
        "the investment that has outperformed the stock market for 200 years",
        "what your net worth should be at every age and why most people fall short",
        "why your employer is hoping you never ask this one question about benefits",
        "the hidden fee inside every mutual fund that quietly eats your returns",
        "what really happens to your credit score when you apply for a loan",
        "why the richest people in the world do not actually earn a salary",
        "the financial concept that separates people who build wealth from those who do not",
        "what compound interest looks like when it works against you instead of for you",
        "why renting is sometimes smarter than buying even when you can afford to",
        "the reason most lottery winners are broke within 5 years",
        "what passive income actually requires that nobody tells you",
        "why insurance companies make money every single year regardless of claims",
        "the tax strategy that wealthy people use that most employees never know about",
        "what happens to the global economy when one country prints too much money",
        "why banks create money out of thin air and what that means for your savings",
        "the rule of 72 that tells you exactly when your money will double",
        "what a 1 percent difference in investment returns does over 30 years",
        "why most financial advice is designed to benefit the advisor not you",
        "the debt payoff method that saves the most money in interest",
        "what happens to the stock market when interest rates go up or down",
        "why keeping too much money in cash is actually a financial risk",
        "the money habit that wealthy people do every single month without fail",
        "what diversification actually means and why most people do it wrong",
        "why your bank charges you fees and exactly how to eliminate them all",
        "the psychological reason people buy things they cannot afford",
        "what a side hustle really costs in time before it becomes profitable",
        "why the stock market always recovers even after massive crashes",
        "the emergency fund rule that every financial expert agrees on",
        "what happens to your retirement if you skip just 5 years of saving",
        "why businesses price things at $9.99 and the psychology behind it",
        "the reason credit scores were invented and who actually benefits from them",
        "what the difference between an asset and a liability really means in practice",
        "why most small businesses fail within 2 years and how to beat those odds",
        "the financial mistake that educated people make more than any other",
        "what dollar cost averaging does to your investment risk over time",
        "why gold keeps its value when everything else loses theirs",
        "the reason financial markets are designed to make individual investors lose",
        "what your spending habits today reveal about your financial future",
        "why getting a raise is less valuable than most people think",
        "the one number that tells you if you will ever be able to retire",
        "what happens to money when a country goes through hyperinflation",
        "why most people overestimate their income and underestimate their expenses",
        "the investment mistake that even experienced traders make in volatile markets",
    ],
    "SCIENCE": [
        "what would happen to earth if the sun disappeared for just one second",
        "the real scientific reason the sky changes colour at sunset",
        "why humans are the only animals on earth that blush from embarrassment",
        "what happens to your body 10 seconds after your heart stops",
        "why time moves faster as you get older according to neuroscience",
        "what the universe looked like in the first second after the big bang",
        "the strange material that is both a solid and a liquid at the same time",
        "why identical twins have completely different fingerprints",
        "what your immune system is actually doing while you sleep at night",
        "the reason some people see colours that others physically cannot",
        "why water molecules act completely differently from every other substance",
        "what a black hole sounds like according to NASA recordings",
        "the scientific reason music gives you chills and what it reveals about your brain",
        "why the ocean is actually darker than space in some places",
        "what happens to your bones in zero gravity over just 6 months",
        "the reason humans are the only species that cooks its food",
        "why every atom in your body was forged inside a dying star",
        "what scientists found when they looked inside a 66-million-year-old egg",
        "the real explanation for why we yawn and why it is contagious",
        "why trees communicate with each other underground through fungi",
        "what the coldest place in the observable universe actually is",
        "the scientific reason certain smells trigger powerful emotional memories",
        "why the human eye can detect a single photon of light in total darkness",
        "what happens to the brain during the final moments of consciousness",
        "the reason some animals can survive being completely frozen solid",
        "why the deep ocean contains creatures that live without any sunlight",
        "what happens when antimatter meets regular matter",
        "the scientific explanation for why we feel pain from emotional experiences",
        "why the same element can be both harmless and lethal depending on the dose",
        "what scientists discovered when they mapped the human brain at full resolution",
        "the reason birds can navigate across continents without any instruments",
        "why certain deep sea fish produce their own light in complete darkness",
        "what would happen if you fell into a black hole from the outside perspective",
        "the scientific reason most people cannot remember anything before age 3",
        "why some sounds make people physically ill even at low volumes",
        "what happens to your sense of time during extremely dangerous situations",
        "the real reason hiccups exist and why science still cannot fully explain them",
        "why the platypus makes scientists rethink everything they know about evolution",
        "what happens to the atmosphere of a planet when it loses its magnetic field",
        "the reason your sense of smell is the most powerful memory trigger",
        "why lightning always takes the same path it took the first time it struck",
        "what scientists found alive inside a 100-million-year-old piece of amber",
        "the reason a sneeze travels faster than most cars on a highway",
        "why the elements inside your body are different from the elements around you",
        "what a nuclear explosion actually looks like from just one mile away",
        "the scientific reason we are drawn to symmetry in everything we see",
        "why researchers believe there may be more water on the moon than on earth",
        "what happens to a human body at the bottom of the deepest trench in the ocean",
        "the reason evolution kept the appendix even though it seems completely useless",
        "why the largest organism on earth is actually a fungus underground",
    ],
}

# ─────────────────────────────────────────────────────────────────────────────
# Logic for WILDCARD clusters (Reddit scraping - the old v4 method)
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_from_reddit() -> List[str]:
    topics  = []
    headers = {"User-Agent": "ai-shorts-bot/1.4"}
    subs    = [
        "todayilearned", "interestingasfuck", "mindblowing",
        "Damnthatsinteresting", "space", "natureismetal", "Awwducational",
        "CreepyWikipedia", "coolguides", "explainlikeimfive", "YouShouldKnow"
    ]
    random.shuffle(subs)
    selected_subs = subs[:4]

    for sub in selected_subs:
        try:
            url  = f"https://www.reddit.com/r/{sub}/top.json?t=week&limit=10"
            resp = requests.get(url, headers=headers, timeout=10)
            if not resp.ok:
                log.warning(f"Reddit r/{sub} failed: HTTP {resp.status_code}")
                continue
            posts = resp.json()["data"]["children"]
            for p in posts:
                title = p["data"]["title"]
                title = re.sub(r"^(TIL|ELI5|YSK|TIL that|TIL:)\s+", "", title, flags=re.IGNORECASE)
                topics.append(title)
        except Exception as e:
            log.warning(f"Reddit r/{sub} failed: {e}")

    log.info(f"  Reddit (Wildcard): {len(topics)} topics from {', '.join(selected_subs)}")
    return topics

def _filter_wildcard_with_gemini(topics: List[str], exclude_topics: Set[str]) -> str:
    if not GEMINI_API_KEY:
        log.warning("No Gemini key — returning first topic as fallback for wildcard")
        return topics[0] if topics else "terrifying deep sea creatures"

    client = genai.Client(api_key=GEMINI_API_KEY)
    topics_list = "\n".join(f"{i+1}. {t}" for i, t in enumerate(topics))
    exclude_list = "\n".join(f"- {t}" for t in exclude_topics)

    prompt = f"""
You are selecting the best topic for a viral YouTube Shorts video.
The channel posts bizarre, shocking, and universally interesting facts.

Trending topics collected today:
{topics_list}

Topics to AVOID (already used recently):
{exclude_list}

Your job:
1. Score each topic 1-10 for its viral potential.
2. Favour topics that are: surprising, visual, emotional, and easily explained.
3. Avoid: politics, celebrities, sports, complex niche topics.
4. Return ONLY the single best topic as a short 2-5 word phrase suitable for a script prompt.
5. If NONE of the topics are good, INVENT a highly viral evergreen topic (e.g. "the most dangerous animal on earth" or "what happens when you die").
6. No explanation, no numbering, just the topic phrase.

Example good output: "why humans forget dreams"
"""
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )
    topic = response.text.strip().strip('"').strip("'")
    log.info(f"  Gemini selected (Wildcard): '{topic}'")
    return topic

def _get_wildcard_topic(seen: set[str]) -> str:
    log.info("[trend_fetcher] Using WILDCARD logic (Reddit + Gemini)")
    reddit_topics = _fetch_from_reddit()
    
    unique_fresh_topics = []
    seen_so_far = set()
    for t in reddit_topics:
        key = t.lower().strip()
        if key and key not in seen_so_far and key not in seen:
            seen_so_far.add(key)
            unique_fresh_topics.append(t)
            
    if not unique_fresh_topics:
        log.warning("All Reddit topics were already seen, using fallback.")
        return "the most mysterious place on earth"
        
    return _filter_wildcard_with_gemini(unique_fresh_topics[:25], seen)

# ─────────────────────────────────────────────────────────────────────────────
# Logic for STRICT niches (pytrends + curated banks)
# ─────────────────────────────────────────────────────────────────────────────

_TREND_SEEDS: dict[str, list[str]] = {
    "AI_TECH":    ["artificial intelligence", "AI technology", "chatgpt", "machine learning"],
    "PSYCHOLOGY": ["psychology facts", "brain science", "mental health", "anxiety"],
    "FINANCE":    ["personal finance", "money tips", "investing", "saving money"],
    "SCIENCE":    ["science facts", "space science", "human body facts", "nature science"],
}

_VIRAL_SCORE_WORDS: dict[str, int] = {
    "why": 2, "how": 2, "what": 1, "secret": 3, "hidden": 3, "truth": 2,
    "never": 2, "always": 1, "wrong": 2, "mistake": 3, "nobody": 3,
    "everyone": 2, "only": 2, "actually": 2, "real": 2, "real reason": 3,
    "scientific": 2, "brain": 2, "money": 2, "ai": 2, "hack": 2,
    "trick": 2, "forever": 2, "dangerous": 2, "impossible": 2, "shocking": 2,
}

def _viral_score(topic: str) -> int:
    tl = topic.lower()
    return sum(w for kw, w in _VIRAL_SCORE_WORDS.items() if kw in tl)

def _try_pytrends(cluster: str, seen_lower: set[str]) -> Optional[str]:
    try:
        from pytrends.request import TrendReq
        seeds = _TREND_SEEDS.get(cluster, ["science facts"])
        seed = random.choice(seeds)

        pt = TrendReq(hl="en-US", tz=330, timeout=(10, 25), retries=2, backoff_factor=0.5)
        pt.build_payload([seed], timeframe="now 7-d", geo="")
        related = pt.related_queries()

        candidates: list[tuple[str, int]] = []
        for result_set in related.values():
            for key in ("top", "rising"):
                df = result_set.get(key)
                if df is None or df.empty: continue
                for _, row in df.iterrows():
                    query: str = str(row.get("query", "")).strip()
                    if len(query) < 8 or query.lower() in seen_lower: continue
                    
                    from pipeline.topic_classifier import _CLUSTER_KEYWORDS
                    cluster_kws = _CLUSTER_KEYWORDS.get(cluster, {})
                    if not any(kw in query.lower() for kw in cluster_kws): continue
                    
                    score = _viral_score(query)
                    candidates.append((query, score))

        if not candidates: return None
        candidates.sort(key=lambda x: -x[1])
        return candidates[0][0]

    except Exception as exc:
        log.warning(f"pytrends failed ({type(exc).__name__}): {exc}")
        return None

def _get_strict_niche_topic(seen: set[str], cluster: str) -> str:
    seen_lower = {s.lower().strip() for s in seen}

    live = _try_pytrends(cluster, seen_lower)
    if live:
        log.info(f"[trend_fetcher] Live trend picked for {cluster}: {live!r}")
        return live

    log.info(f"[trend_fetcher] Using curated bank for cluster {cluster}")
    bank = list(_TOPIC_BANKS.get(cluster, _TOPIC_BANKS["SCIENCE"]))
    random.shuffle(bank)
    bank.sort(key=lambda t: -_viral_score(t))

    for topic in bank:
        if topic.lower().strip() not in seen_lower:
            log.info(f"[trend_fetcher] Curated topic picked: {topic!r}")
            return topic

    random.shuffle(bank)
    for topic in bank:
        if topic.lower().strip() not in seen_lower:
            return topic

    raise RuntimeError(f"All {len(bank)} topics for cluster {cluster!r} have been used.")

# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def get_trending_topic(seen: set[str], cluster: str = "SCIENCE") -> str:
    """
    Return a fresh topic string for the given niche cluster.
    Routes to either strict niche logic or wildcard logic based on cluster name.
    """
    if cluster.startswith("VIRAL_FACTS"):
        return _get_wildcard_topic(seen)
    else:
        return _get_strict_niche_topic(seen, cluster)
