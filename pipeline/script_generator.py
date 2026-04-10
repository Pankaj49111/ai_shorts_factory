"""
script_generator.py — Viral Shorts Script Generator v4 (Viral Optimized)
========================================================================
Root cause of v2/v3 failures (now fixed):
  The google-genai SDK was routing "gemini-2.0-flash" → "gemini-2.5-flash",
  which is a *thinking model*. Thinking tokens consumed most of the
  max_output_tokens budget, leaving only 30-60 words for actual output —
  causing every attempt to fail the 100-140 word check.

Fixes applied:
  1. Primary model: gemini-2.5-flash  (recommended for fast script generation)
     Fallback models: gemini-2.0-flash-lite, gemini-1.5-flash
  2. thinking_budget=0 injected wherever supported (kills thinking tokens)
  3. max_output_tokens raised to 3000 (generous headroom for both models)
  4. Prompt is self-contained in a single string (no system_instruction quirks)
  5. Clean-output is non-destructive: only strips pure label lines

Free tier (gemini-2.5-flash): Check Google AI Studio for current limits.
"""

from __future__ import annotations

import logging
import os
import re
import time
import random

log = logging.getLogger("pipeline.script_generator")

# ── Models to try in order ────────────────────────────────────────────────────
# gemini-2.5-flash: recommended for fast script generation
_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash-lite", "gemini-1.5-flash"]

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
# Written to leave the model NO room to do internal reasoning in the output.
# The EXAMPLE at the end is the single most reliable technique to get correct
# length — models match example length more reliably than they follow word counts.
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


def _call_gemini(prompt: str, model: str, temperature: float = 0.75) -> str:
    """
    Call Gemini API with the given model and temperature.
    Explicitly disables thinking tokens (budget=0) to prevent
    gemini-2.5-flash from consuming output budget on internal reasoning.
    """
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError(
            "google-genai not installed. Run: pip install google-genai"
        ) from exc

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY missing from .env\n"
            "Get a free key at https://aistudio.google.com/app/apikey"
        )

    client = genai.Client(api_key=api_key)

    # Build config — try with thinking_budget=0 first, fall back without it
    # (thinking_budget is only valid on thinking-capable models)
    config_with_no_thinking = None
    try:
        config_with_no_thinking = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=3000,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )
    except (AttributeError, TypeError):
        pass   # ThinkingConfig not available in this SDK version

    config_default = types.GenerateContentConfig(
        temperature=temperature,
        max_output_tokens=3000,
    )

    # Try no-thinking config first, then default
    for cfg in filter(None, [config_with_no_thinking, config_default]):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=cfg,
            )
            text = (response.text or "").strip()
            if text:
                return text
        except Exception as exc:
            log.debug(f"[script_gen] Config attempt failed ({type(exc).__name__}): {exc}")
            continue

    raise RuntimeError(f"No response from model {model!r}")


def _clean_output(raw: str) -> str:
    """
    Remove ONLY pure label lines and leading label prefixes.
    Never discards content words — previous versions were too aggressive.
    """
    if not raw:
        return ""

    # Lines that are ONLY a label (nothing else) — safe to drop entirely
    label_only = re.compile(
        r"^\s*\*{0,2}\s*"
        r"(hook|section\s*\d*|build|payoff|cta|intro|outro|opening|closing"
        r"|script|word\s*count|word count check|example)"
        r"[\s\:\-\—]*\*{0,2}\s*$",
        re.IGNORECASE,
    )

    # Strip only a leading label prefix, keep the rest of the line
    strip_prefix = re.compile(
        r"^\s*\*{0,2}"
        r"(hook|section\s*\d*|build|payoff|cta|opening|closing)"
        r"\s*[\:\-\—]\s*\*{0,2}\s*",
        re.IGNORECASE,
    )

    # Markdown heading
    md_heading = re.compile(r"^\s*#{1,4}\s+", re.IGNORECASE)

    # If the model outputs its own "word count" meta-commentary at the end,
    # everything from "Word count:" / "Word Count Check:" onward is noise.
    # Find that boundary and truncate.
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
    """
    Generate a 70-105 word YouTube Shorts script for the given topic.

    Args:
        topic:   Topic string to write about.
        cluster: Niche cluster — controls context, tone, and CTA.

    Returns:
        Script string ready for TTS voice generation.

    Raises:
        RuntimeError: If no usable script produced after all attempts.
    """
    base_prompt = _build_prompt(topic, cluster)
    best_script = ""
    best_wc     = 0

    # Define word count targets consistent with pipeline_runner.py
    min_words = 70
    max_words = 105

    for model in _MODELS:
        log.info(f"[script_gen] Trying model: {model}")
        prompt = base_prompt
        
        # Pick a random temperature between 0.75 and 0.95 for the initial run
        current_temp = round(random.uniform(0.75, 0.95), 2)

        for attempt in range(1, 5):
            # Fall back to a safer, fixed temperature for retries
            if attempt > 1:
                current_temp = 0.75
                
            log.info(f"[script_gen] Generation attempt {attempt} with temperature {current_temp}")

            try:
                raw    = _call_gemini(prompt, model, temperature=current_temp)
                script = _clean_output(raw)
                wc     = _word_count(script)

                log.info(
                    f"[script_gen] {model} attempt {attempt} (temp {current_temp}) → {wc} words"
                )

                if wc > best_wc:
                    best_wc     = wc
                    best_script = script

                # FIX: Use the new min/max word counts for the acceptance criteria
                if min_words <= wc <= max_words + 5: # Allow a small buffer
                    log.info(f"[script_gen] Accepted: {wc} words | {model} | temp {current_temp}")
                    return script

                # Show raw preview only when failing to help debug
                log.warning(
                    f"[script_gen] {wc} words — outside {min_words}-{max_words} target.\n"
                    f"  Raw preview: {raw[:250]!r}"
                )

                # FIX: Update corrective prompts to use the new word count targets
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

                # Rate limit: flash models generally have higher RPM than pro models
                sleep_sec = 4 if "flash" in model else 8
                time.sleep(sleep_sec)

            except Exception as exc:
                log.error(
                    f"[script_gen] {model} attempt {attempt} error: {exc}"
                )
                time.sleep(8)

    # Graceful fallback — if we got at least 60 words, use it rather than crash
    if best_script and best_wc >= 60:
        log.warning(
            f"[script_gen] All models exhausted. Returning best-effort script: "
            f"{best_wc} words. Pipeline will continue."
        )
        return best_script

    raise RuntimeError(
        f"Script generation failed for: {topic!r}\n"
        f"Best word count across all models: {best_wc} words.\n"
        f"Check GEMINI_API_KEY at https://aistudio.google.com/app/apikey\n"
        f"Check quota: https://aistudio.google.com/app/usage"
    )
