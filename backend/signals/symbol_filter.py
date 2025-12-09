# backend/signals/symbol_filter.py
"""
Universal symbol filtering for all asset types.

This module provides a unified interface for filtering events by symbol relevance,
routing to appropriate domain-specific filters based on symbol prefix or pattern.

Used by:
- feature_extractor.py for event-based forecasting
- Any other module that needs symbol-specific event filtering
"""

import re
from typing import Optional


def is_symbol_mentioned(event_text: str, symbol: str) -> bool:
    """
    Universal symbol mention checker.

    Routes to domain-specific filters based on symbol format:
    - NFL:TEAM_NAME → NFL team filter (e.g., NFL:DAL_COWBOYS)
    - TICKER-USD → Crypto filter (e.g., BTC-USD, ETH-USD)
    - Other → Generic pattern matching (e.g., NVDA, TSLA)

    Args:
        event_text: Event title/summary/clean_text to search
        symbol: Symbol to check for (e.g., "BTC-USD", "NFL:DAL_COWBOYS", "NVDA")

    Returns:
        True if symbol is mentioned in event text, False otherwise

    Examples:
        >>> is_symbol_mentioned("Bitcoin surges past $100k", "BTC-USD")
        True
        >>> is_symbol_mentioned("Cowboys win playoff game", "NFL:DAL_COWBOYS")
        True
        >>> is_symbol_mentioned("Nvidia releases new chip", "NVDA")
        True
        >>> is_symbol_mentioned("Ethereum news", "BTC-USD")
        False
    """
    if not event_text or not symbol:
        return False

    # Route by symbol prefix/format
    if symbol.startswith("NFL:"):
        # NFL team symbols
        from signals.nfl_features import is_team_mentioned
        return is_team_mentioned(event_text, symbol)

    elif symbol.endswith("-USD") or symbol in ["BTC", "ETH", "XMR", "SOL", "AVAX"]:
        # Crypto symbols
        from signals.crypto_features import is_symbol_mentioned as crypto_filter
        return crypto_filter(event_text, symbol)

    else:
        # Generic fallback: check if symbol appears as word in text
        # This works for equity tickers (NVDA, TSLA, AAPL, etc.)
        pattern = rf"\b{re.escape(symbol)}\b"
        return bool(re.search(pattern, event_text, re.IGNORECASE))


def get_symbol_domain(symbol: str) -> Optional[str]:
    """
    Get the domain category for a symbol.

    Args:
        symbol: Symbol to categorize

    Returns:
        Domain string ("crypto", "sports", "tech", etc.) or None

    Examples:
        >>> get_symbol_domain("BTC-USD")
        'crypto'
        >>> get_symbol_domain("NFL:DAL_COWBOYS")
        'sports'
        >>> get_symbol_domain("NVDA")
        'tech'
    """
    if symbol.startswith("NFL:"):
        return "sports"
    elif symbol.endswith("-USD") or symbol in ["BTC", "ETH", "XMR", "SOL", "AVAX"]:
        return "crypto"
    elif symbol in ["NVDA", "TSLA", "AAPL", "MSFT", "GOOGL", "AMZN"]:
        return "tech"
    else:
        return None


if __name__ == "__main__":
    # Test universal filtering
    print("Testing universal symbol filtering...\n")

    test_cases = [
        # (text, symbol, expected_result)
        ("Bitcoin price surges to $100k", "BTC-USD", True),
        ("Ethereum merge complete", "ETH-USD", True),
        ("Bitcoin price surges to $100k", "ETH-USD", False),
        ("Dallas Cowboys win playoff game", "NFL:DAL_COWBOYS", True),
        ("Kansas City Chiefs victory", "NFL:KC_CHIEFS", True),
        ("Cowboys news", "NFL:KC_CHIEFS", False),
        ("Nvidia releases new AI chip", "NVDA", True),
        ("Tesla stock jumps", "TSLA", True),
        ("Nvidia releases new AI chip", "TSLA", False),
    ]

    passed = 0
    failed = 0

    for text, symbol, expected in test_cases:
        result = is_symbol_mentioned(text, symbol)
        status = "✓" if result == expected else "✗"
        if result == expected:
            passed += 1
        else:
            failed += 1

        print(f"{status} '{text[:40]}...' → {symbol}: {result} (expected {expected})")

    print(f"\n{passed} passed, {failed} failed")

    # Test domain detection
    print("\n\nTesting domain detection...")
    symbols = ["BTC-USD", "ETH-USD", "NFL:DAL_COWBOYS", "NFL:KC_CHIEFS", "NVDA", "UNKNOWN"]
    for sym in symbols:
        domain = get_symbol_domain(sym)
        print(f"  {sym} → {domain}")
