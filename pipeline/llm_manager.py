import os
import logging
import time

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("pipeline.llm_manager")

# Initialize SDKs lazily
_gemini_client = None
_groq_client = None
_cerebras_client = None

def _get_gemini_client():
    global _gemini_client
    if not _gemini_client:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in .env")
        from google import genai
        _gemini_client = genai.Client(api_key=api_key)
    return _gemini_client

def _get_groq_client():
    global _groq_client
    if not _groq_client:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY not found in .env")
        from groq import Groq
        _groq_client = Groq(api_key=api_key)
    return _groq_client

def _get_cerebras_client():
    global _cerebras_client
    if not _cerebras_client:
        api_key = os.getenv("CEREBRAS_API_KEY")
        if not api_key:
            raise ValueError("CEREBRAS_API_KEY not found in .env")
        from cerebras.cloud.sdk import Cerebras
        _cerebras_client = Cerebras(api_key=api_key)
    return _cerebras_client


def _call_gemini(prompt: str, temperature: float = 0.7, max_tokens: int = 3000) -> str:
    client = _get_gemini_client()
    from google.genai import types
    
    config_with_no_thinking = None
    try:
        config_with_no_thinking = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )
    except (AttributeError, TypeError):
        pass

    config_default = types.GenerateContentConfig(
        temperature=temperature,
        max_output_tokens=max_tokens,
    )

    last_error = None
    for cfg in filter(None, [config_with_no_thinking, config_default]):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=cfg,
            )
            text = (response.text or "").strip()
            if text:
                return text
        except Exception as exc:
            log.debug(f"Gemini config attempt failed: {exc}")
            last_error = exc
            continue
            
    if last_error:
        raise last_error
    raise RuntimeError("Gemini returned empty response.")


def _call_groq(prompt: str, model: str = "llama-3.3-70b-versatile", temperature: float = 0.7, max_tokens: int = 3000) -> str:
    client = _get_groq_client()
    response = client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=False
    )
    # response should be a ChatCompletion, not a Stream
    if hasattr(response, 'choices') and response.choices:
        text = response.choices[0].message.content
        if text:
            return text.strip()
    raise RuntimeError("Groq returned empty response.")


def _call_cerebras(prompt: str, model: str = "llama3.1-8b", temperature: float = 0.7, max_tokens: int = 3000) -> str:
    client = _get_cerebras_client()
    response = client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        temperature=temperature,
        max_completion_tokens=max_tokens,
        stream=False
    )
    if hasattr(response, 'choices') and response.choices:
        text = response.choices[0].message.content
        if text:
            return text.strip()
    raise RuntimeError("Cerebras returned empty response.")


def generate_completion(prompt: str, task_type: str = "script", temperature: float = 0.75, max_tokens: int = 3000) -> str:
    """
    Generates text using a fallback cascade.
    task_type: "script" or "utility"
    """
    if task_type == "script":
        # Hierarchy: Gemini -> Groq -> Cerebras
        hierarchy = [
            ("Gemini (gemini-2.5-flash)", lambda: _call_gemini(prompt, temperature, max_tokens)),
            ("Groq (llama-3.3-70b-versatile)", lambda: _call_groq(prompt, "llama-3.3-70b-versatile", temperature, max_tokens)),
            ("Cerebras (llama3.1-8b)", lambda: _call_cerebras(prompt, "llama3.1-8b", temperature, max_tokens)),
        ]
    elif task_type == "utility":
        # Hierarchy: Groq -> Cerebras -> Gemini
        hierarchy = [
            ("Groq (llama-3.1-8b-instant)", lambda: _call_groq(prompt, "llama-3.1-8b-instant", temperature, max_tokens)),
            ("Cerebras (llama3.1-8b)", lambda: _call_cerebras(prompt, "llama3.1-8b", temperature, max_tokens)),
            ("Gemini (gemini-2.5-flash)", lambda: _call_gemini(prompt, temperature, max_tokens)),
        ]
    else:
        raise ValueError(f"Unknown task_type: {task_type}")

    last_error = None
    for name, call_fn in hierarchy:
        try:
            log.info(f"[{task_type}] Trying {name}...")
            result = call_fn()
            
            # Clean markdown code blocks if the model wrapped it (mostly for json/lists)
            result = result.strip()
            if result.startswith("```"):
                lines = result.split("\n")
                if len(lines) >= 2 and lines[-1].strip() == "```":
                    result = "\n".join(lines[1:-1]).strip()
            
            return result
        except Exception as e:
            log.warning(f"[{task_type}] {name} failed: {e}")
            last_error = e
            time.sleep(2) # Short delay before fallback

    raise RuntimeError(f"All models failed for task '{task_type}'. Last error: {last_error}")