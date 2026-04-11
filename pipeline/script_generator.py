"""
script_generator.py — Viral Shorts Script Generator v4 (Viral Optimized)
========================================================================
Now using llm_manager for robust model fallback (Gemini -> Groq -> Cerebras).
"""

from __future__ import annotations

import logging
import re
import time
import random

from pipeline.llm_manager import generate_completion

log = logging.getLogger("pipeline.script_generator")

# ── Cluster context + CTA ─────────────────────────────────────────────────────
_CLUSTER_CONTEXT: dict[str, str] = {
    "TECH_SECRETS": (
        "NICHE: Consumer tech secrets, privacy, and hardware glitches. "
        "Reference real hidden features in smartphones, consoles (PS5/Xbox), or data tracking. "
        "NO abstract software, NO AI, NO ChatGPT. Focus on physical tech users hold in their hands."
    ),
    "BRAIN_SCIENCE": (
        "NICHE: Neurological science and physical brain oddities. "
        "Reference real neuroscience studies about memory, sleep, or physical brain changes. "
        "NO vague behavioral psychology or mental health advice. Focus on the brain as a biological machine."
    ),
    "BIOLOGY_NATURE": (
        "NICHE: Bizarre animal adaptations and human body oddities. "
        "Reference real, shocking facts about insects, deep sea creatures, parasites, or human organs. "
        "Make it sound like a sci-fi horror movie, but keep it 100% scientifically accurate."
    ),
    "SCIENCE": (
        "NICHE: Science and nature mysteries. Reference real phenomena, discoveries, "
        "or counterintuitive facts about the universe, physics, or chemistry. "
        "Use vivid analogies to make complex ideas tangible."
    ),
    "VIRAL_FACTS_1": (
        "NICHE: Shocking, bizarre, and universally appealing facts. "
        "These facts must sound almost fake but be 100% real. Focus on high "
        "emotional impact, extreme oddities in nature, history, or reality."
    ),
    "VIRAL_FACTS_2": (
        "NICHE: Shocking, bizarre, and universally appealing facts. "
        "These facts must sound almost fake but be 100% real. Focus on high "
        "emotional impact, extreme oddities in nature, history, or reality."
    ),
}

_CLUSTER_CTA: dict[str, str] = {
    "TECH_SECRETS":   "Follow for daily tech secrets they don't want you to know.",
    "BRAIN_SCIENCE":  "Follow for daily brain facts that will blow your mind.",
    "BIOLOGY_NATURE": "Follow for daily bizarre biology facts you won't believe.",
    "SCIENCE":        "Follow for daily science facts that actually exist.",
    "VIRAL_FACTS_1":  "Follow for daily bizarre facts that actually exist.",
    "VIRAL_FACTS_2":  "Follow for daily bizarre facts that actually exist.",
}

# ── Prompt ────────────────────────────────────────────────────────────────────
_PROMPT_TEMPLATE = """\
You are a YouTube Shorts script writer. Write a spoken script for the topic below.

TOPIC: "{topic}"

{cluster_context}

ABSOLUTE REQUIREMENTS:
- Output ONLY the spoken script. Nothing else. No labels, no markdown, no \
"Hook:", no "Section:", no word counts, no explanations, no preamble.
- Total word count: EXACTLY 70 to 105 words. Not 30. Not 50. Not 120. \
Between 70 and 105 words.
- Short sentences. Maximum 12 words per sentence.
- Plain English. No idioms. No cultural references.
- Do NOT start with the topic name.

STRUCTURE (write as plain spoken paragraphs — NO section labels):
1. Opening hook (8-14 words): Start with one of these:
   "You have been wrong about [X] your whole life."
   "The real reason [X] will genuinely surprise you."
   "[Specific number or fact]. Science finally has an answer."
   "Nobody ever explains why [X] actually happens."
   "Most people learn this too late — [surprising claim]."

2. Core insight (30-50 words): Give the main fact or mechanism. Include 1 or 2 \
specific numbers, named studies, or precise details. Build toward the payoff.

3. Payoff (25-45 words): The surprising conclusion or actionable takeaway. \
What viewers will save or share. End with a memorable sentence.

4. Final line (copy exactly, do not change a single word):
{cta}

EXAMPLE of correct format and correct length — notice it is flowing prose with \
NO labels, starts with a hook, ends with the CTA:

You have been wrong about octopus intelligence your whole life. Octopuses have \
three hearts and nine brains — one central brain plus one for each arm. A 2021 \
Cambridge study found each arm solves problems independently, even while \
disconnected from the central brain. They are not one creature thinking — they \
are nine creatures cooperating. Follow for more mind-blowing facts every single day.

Now write the script for the topic "{topic}". \
Remember: 70-105 words, no labels, spoken prose only.\
"""


def _build_prompt(topic: str, cluster: str) -> str:
    ctx = _CLUSTER_CONTEXT.get(cluster, _CLUSTER_CONTEXT["SCIENCE"])
    cta = _CLUSTER_CTA.get(cluster, "Follow for more facts every single day.")
    return _PROMPT_TEMPLATE.format(
        topic=topic,
        cluster_context=ctx,
        cta=cta,
    )


def _clean_output(raw: str) -> str:
    if not raw:
        return ""

    label_only = re.compile(
        r"^\s*\*{0,2}\s*"
        r"(hook|section\s*\d*|build|payoff|cta|intro|outro|opening|closing"
        r"|script|word\s*count|word count check|example)"
        r"[\s\:\-\—]*\*{0,2}\s*$",
        re.IGNORECASE,
    )

    strip_prefix = re.compile(
        r"^\s*\*{0,2}"
        r"(hook|section\s*\d*|build|payoff|cta|opening|closing)"
        r"\s*[\:\-\—]\s*\*{0,2}\s*",
        re.IGNORECASE,
    )

    md_heading = re.compile(r"^\s*#{1,4}\s+", re.IGNORECASE)

    word_count_boundary = re.compile(
        r"\n\s*(word\s*count|word count check|total words|counting)[:\s]",
        re.IGNORECASE,
    )
    match = word_count_boundary.search(raw)
    if match:
        raw = raw[: match.start()]

    cleaned: list[str] = []
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        if label_only.match(s):
            continue
        s = strip_prefix.sub("", s).strip()
        s = md_heading.sub("", s).strip()
        if s:
            cleaned.append(s)

    return " ".join(cleaned).strip()


def _word_count(text: str) -> int:
    return len(text.split()) if text else 0


def generate_script(topic: str, cluster: str = "SCIENCE") -> str:
    base_prompt = _build_prompt(topic, cluster)
    best_script = ""
    best_wc     = 0

    min_words = 70
    max_words = 105

    prompt = base_prompt
    current_temp = round(random.uniform(0.75, 0.95), 2)

    for attempt in range(1, 6):
        if attempt > 1:
            current_temp = 0.75
            
        log.info(f"[script_gen] Generation attempt {attempt} with temperature {current_temp}")

        try:
            raw = generate_completion(prompt, task_type="script", temperature=current_temp)
            script = _clean_output(raw)
            wc = _word_count(script)

            log.info(f"[script_gen] attempt {attempt} (temp {current_temp}) → {wc} words")

            if wc > best_wc:
                best_wc = wc
                best_script = script

            if min_words <= wc <= max_words + 5:
                log.info(f"[script_gen] Accepted: {wc} words | temp {current_temp}")
                return script

            log.warning(
                f"[script_gen] {wc} words — outside {min_words}-{max_words} target.\n"
                f"  Raw preview: {raw[:250]!r}"
            )

            if wc < min_words:
                shortfall = min_words + 5 - wc
                prompt = (
                    f"{base_prompt}\n\n"
                    f"YOUR PREVIOUS ATTEMPT WAS {wc} WORDS — TOO SHORT.\n"
                    f"You need approximately {shortfall} MORE words.\n"
                    f"Expand the Core Insight and Payoff sections.\n"
                    f"The script must be {min_words} to {max_words} words total.\n"
                    f"Do not include labels. Write the complete script now."
                )
            else:
                excess = wc - max_words
                prompt = (
                    f"{base_prompt}\n\n"
                    f"YOUR PREVIOUS ATTEMPT WAS {wc} WORDS — TOO LONG BY ~{excess} WORDS.\n"
                    f"Cut filler words. Target {min_words} to {max_words} words total.\n"
                    f"Write the complete script now."
                )

            time.sleep(2)

        except Exception as exc:
            log.error(f"[script_gen] attempt {attempt} error: {exc}")
            time.sleep(4)

    if best_script and best_wc >= 60:
        log.warning(
            f"[script_gen] All attempts exhausted. Returning best-effort script: "
            f"{best_wc} words. Pipeline will continue."
        )
        return best_script

    raise RuntimeError(
        f"Script generation failed for: {topic!r}\n"
        f"Best word count: {best_wc} words."
    )
