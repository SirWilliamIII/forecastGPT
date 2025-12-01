# backend/llm/providers.py
"""
Multi-provider LLM abstraction with retry logic and thread-safe initialization.

Usage:
    from llm import complete, analyze_event, classify_sentiment

    # General completion
    response = complete("Summarize this article...", provider="claude")

    # Event analysis (uses Claude by default - best for reasoning)
    analysis = analyze_event(event_text, symbol="BTC-USD")

    # Sentiment classification (uses Gemini by default - fast + cheap)
    sentiment = classify_sentiment(headline)
"""

import os
import time
import threading
from enum import Enum
from typing import Optional, Literal
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


class LLMProvider(Enum):
    OPENAI = "openai"
    CLAUDE = "claude"
    GEMINI = "gemini"


@dataclass
class LLMResponse:
    text: str
    provider: LLMProvider
    model: str
    tokens_used: Optional[int] = None


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MAX_LLM_RETRIES = int(os.getenv("MAX_LLM_RETRIES", "3"))
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "20.0"))
MAX_CONCURRENT_LLM_CALLS = int(os.getenv("MAX_CONCURRENT_LLM_CALLS", "5"))

# ---------------------------------------------------------------------------
# Thread-safe provider clients (lazy-loaded)
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_openai_client = None
_anthropic_client = None
_gemini_model = None
_llm_semaphore = threading.Semaphore(MAX_CONCURRENT_LLM_CALLS)


def _get_openai():
    global _openai_client
    if _openai_client is None:
        with _lock:
            if _openai_client is None:
                from openai import OpenAI
                key = os.getenv("OPENAI_API_KEY")
                if not key:
                    raise ValueError("OPENAI_API_KEY not set")
                _openai_client = OpenAI(api_key=key, timeout=LLM_TIMEOUT)
    return _openai_client


def _get_anthropic():
    global _anthropic_client
    if _anthropic_client is None:
        with _lock:
            if _anthropic_client is None:
                import anthropic
                key = os.getenv("ANTHROPIC_API_KEY")
                if not key:
                    raise ValueError("ANTHROPIC_API_KEY not set")
                _anthropic_client = anthropic.Anthropic(api_key=key)
    return _anthropic_client


def _get_gemini():
    global _gemini_model
    if _gemini_model is None:
        with _lock:
            if _gemini_model is None:
                import google.generativeai as genai
                key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
                if not key:
                    raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY not set")
                genai.configure(api_key=key)
                _gemini_model = genai.GenerativeModel("gemini-1.5-flash")
    return _gemini_model


def get_provider(name: str) -> LLMProvider:
    """Get provider enum from string."""
    return LLMProvider(name.lower())


# ---------------------------------------------------------------------------
# Core completion function with concurrency limiting
# ---------------------------------------------------------------------------


def complete(
    prompt: str,
    provider: Literal["openai", "claude", "gemini"] = "claude",
    system: Optional[str] = None,
    max_tokens: int = 1024,
    temperature: float = 0.7,
) -> LLMResponse:
    """
    Send a completion request to the specified provider.

    Args:
        prompt: The user prompt
        provider: Which LLM to use (openai, claude, gemini)
        system: Optional system prompt
        max_tokens: Maximum response tokens
        temperature: Sampling temperature

    Returns:
        LLMResponse with text and metadata

    Raises:
        ValueError: If provider fails after retries (for HTTP 503 mapping)
    """
    with _llm_semaphore:
        if provider == "openai":
            return _complete_openai(prompt, system, max_tokens, temperature)
        elif provider == "claude":
            return _complete_claude(prompt, system, max_tokens, temperature)
        elif provider == "gemini":
            return _complete_gemini(prompt, system, max_tokens, temperature)
        else:
            raise ValueError(f"Unknown provider: {provider}")


def _complete_openai(
    prompt: str,
    system: Optional[str],
    max_tokens: int,
    temperature: float,
) -> LLMResponse:
    from openai import APIError, RateLimitError, APITimeoutError

    client = _get_openai()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    last_error: Exception | None = None

    for attempt in range(MAX_LLM_RETRIES):
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return LLMResponse(
                text=response.choices[0].message.content or "",
                provider=LLMProvider.OPENAI,
                model="gpt-4o-mini",
                tokens_used=response.usage.total_tokens if response.usage else None,
            )
        except (RateLimitError, APITimeoutError, APIError) as e:
            last_error = e
            if attempt < MAX_LLM_RETRIES - 1:
                delay = 1.0 * (2 ** attempt)
                print(f"[llm] OpenAI error ({e}); retrying in {delay:.1f}s...")
                time.sleep(delay)

    raise ValueError(f"OpenAI error after {MAX_LLM_RETRIES} retries: {last_error}")


def _complete_claude(
    prompt: str,
    system: Optional[str],
    max_tokens: int,
    temperature: float,
) -> LLMResponse:
    import anthropic

    client = _get_anthropic()

    kwargs = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        kwargs["system"] = system

    last_error: Exception | None = None

    for attempt in range(MAX_LLM_RETRIES):
        try:
            response = client.messages.create(**kwargs)
            text = ""
            if response.content:
                text = response.content[0].text

            return LLMResponse(
                text=text,
                provider=LLMProvider.CLAUDE,
                model="claude-sonnet-4-20250514",
                tokens_used=response.usage.input_tokens + response.usage.output_tokens,
            )
        except anthropic.APIError as e:
            last_error = e
            if attempt < MAX_LLM_RETRIES - 1:
                delay = 1.0 * (2 ** attempt)
                print(f"[llm] Claude error ({e}); retrying in {delay:.1f}s...")
                time.sleep(delay)

    raise ValueError(f"Claude error after {MAX_LLM_RETRIES} retries: {last_error}")


def _complete_gemini(
    prompt: str,
    system: Optional[str],
    max_tokens: int,
    temperature: float,
) -> LLMResponse:
    model = _get_gemini()

    full_prompt = prompt
    if system:
        full_prompt = f"{system}\n\n{prompt}"

    last_error: Exception | None = None

    for attempt in range(MAX_LLM_RETRIES):
        try:
            response = model.generate_content(
                full_prompt,
                generation_config={
                    "max_output_tokens": max_tokens,
                    "temperature": temperature,
                },
                request_options={"timeout": LLM_TIMEOUT},
            )
            return LLMResponse(
                text=response.text,
                provider=LLMProvider.GEMINI,
                model="gemini-1.5-flash",
                tokens_used=None,
            )
        except Exception as e:
            last_error = e
            if attempt < MAX_LLM_RETRIES - 1:
                delay = 1.0 * (2 ** attempt)
                print(f"[llm] Gemini error ({e}); retrying in {delay:.1f}s...")
                time.sleep(delay)

    raise ValueError(f"Gemini error after {MAX_LLM_RETRIES} retries: {last_error}")


# ---------------------------------------------------------------------------
# High-level functions for specific use cases
# ---------------------------------------------------------------------------


def analyze_event(
    event_text: str,
    symbol: str = "BTC-USD",
    provider: Literal["openai", "claude", "gemini"] = "claude",
) -> dict:
    """
    Analyze a news event for market impact.

    Uses Claude by default (best for nuanced reasoning).

    Returns:
        dict with sentiment, impact_score, reasoning, tags
    """
    system = """You are a financial analyst specializing in crypto markets.
Analyze news events for their potential market impact.
Respond in JSON format with these fields:
- sentiment: "bullish", "bearish", or "neutral"
- impact_score: float from -1.0 (very bearish) to 1.0 (very bullish)
- confidence: float from 0.0 to 1.0
- reasoning: brief explanation (1-2 sentences)
- tags: list of relevant tags (e.g., ["regulation", "adoption", "macro"])
"""

    prompt = f"""Analyze this event for {symbol}:

{event_text}

Respond with valid JSON only."""

    response = complete(prompt, provider=provider, system=system, temperature=0.3)

    import json
    try:
        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
    except json.JSONDecodeError:
        return {
            "sentiment": "neutral",
            "impact_score": 0.0,
            "confidence": 0.0,
            "reasoning": "Failed to parse LLM response",
            "tags": [],
            "raw_response": response.text,
        }


def classify_sentiment(
    text: str,
    provider: Literal["openai", "claude", "gemini"] = "gemini",
) -> Literal["positive", "negative", "neutral"]:
    """
    Quick sentiment classification.

    Uses Gemini by default (fast + cheap for simple tasks).

    Returns:
        "positive", "negative", or "neutral"
    """
    prompt = f"""Classify the sentiment of this text as exactly one of: positive, negative, neutral

Text: {text}

Respond with only one word: positive, negative, or neutral"""

    response = complete(prompt, provider=provider, max_tokens=10, temperature=0.0)

    result = response.text.strip().lower()
    if result in ("positive", "negative", "neutral"):
        return result
    return "neutral"


def summarize_events(
    events: list[str],
    provider: Literal["openai", "claude", "gemini"] = "claude",
) -> str:
    """
    Summarize multiple events into a market narrative.

    Uses Claude by default (best for synthesis).
    """
    system = """You are a financial news analyst.
Synthesize multiple news events into a coherent market narrative.
Be concise but insightful. Focus on market implications."""

    events_text = "\n\n---\n\n".join(events)
    prompt = f"""Summarize these recent events and their potential market impact:

{events_text}

Provide a 2-3 paragraph synthesis."""

    response = complete(prompt, provider=provider, system=system, max_tokens=500)
    return response.text
