# backend/llm/__init__.py
"""
Multi-provider LLM module.

Supports:
- OpenAI (embeddings, chat)
- Anthropic Claude (analysis, reasoning)
- Google Gemini (long context, multimodal)
"""

from .providers import (
    get_provider,
    complete,
    analyze_event,
    classify_sentiment,
    LLMProvider,
)

__all__ = [
    "get_provider",
    "complete",
    "analyze_event",
    "classify_sentiment",
    "LLMProvider",
]
