# backend/signals/crypto_features.py
"""
Crypto-specific feature extraction and symbol filtering.

This module provides symbol-specific filtering for crypto events,
ensuring BTC forecasts use BTC events, ETH uses ETH, etc.
"""

import re
from typing import List, Optional

# Symbol mention patterns (case-insensitive)
CRYPTO_SYMBOL_PATTERNS = {
    "BTC-USD": [
        r"\bBTC\b",
        r"\bBitcoin\b",
        r"\bBTC-USD\b",
        r"\bXBT\b",  # Alternative ticker
    ],
    "ETH-USD": [
        r"\bETH\b",
        r"\bEthereum\b",
        r"\bETH-USD\b",
        r"\bEther\b",
    ],
    "XMR-USD": [
        r"\bXMR\b",
        r"\bMonero\b",
        r"\bXMR-USD\b",
    ],
}


def is_symbol_mentioned(
    event_text: str,
    symbol: str,
    case_sensitive: bool = False,
) -> bool:
    """
    Check if event text mentions a specific crypto symbol.

    Args:
        event_text: Event title/summary/clean_text
        symbol: Symbol (e.g., "BTC-USD")
        case_sensitive: Whether to use case-sensitive matching

    Returns:
        True if symbol is mentioned, False otherwise
    """
    patterns = CRYPTO_SYMBOL_PATTERNS.get(symbol, [])
    if not patterns:
        # Symbol not configured - allow through (fallback to semantic similarity only)
        return True

    flags = 0 if case_sensitive else re.IGNORECASE

    for pattern in patterns:
        if re.search(pattern, event_text, flags):
            return True

    return False


def get_symbol_events(
    events: List[dict],
    symbol: str,
) -> List[dict]:
    """
    Filter events to only those mentioning the symbol.

    Args:
        events: List of event dicts with 'title', 'summary', 'clean_text'
        symbol: Symbol to filter for

    Returns:
        Filtered list of events
    """
    filtered = []

    for event in events:
        # Build text to check
        text_to_check = " ".join(filter(None, [
            event.get('title', ''),
            event.get('summary', ''),
            event.get('clean_text', ''),
        ]))

        if is_symbol_mentioned(text_to_check, symbol):
            filtered.append(event)

    return filtered


if __name__ == "__main__":
    # Test filtering
    test_events = [
        {"title": "Bitcoin price surges to new high", "summary": "BTC reaches $100k"},
        {"title": "Ethereum merge complete", "summary": "ETH transitions to PoS"},
        {"title": "Crypto market overview", "summary": "BTC and ETH both up"},
        {"title": "Monero privacy update", "summary": "XMR improves anonymity"},
    ]

    print("Testing symbol filtering...")
    print("\nBTC-USD events:")
    btc_events = get_symbol_events(test_events, "BTC-USD")
    for evt in btc_events:
        print(f"  - {evt['title']}")

    print("\nETH-USD events:")
    eth_events = get_symbol_events(test_events, "ETH-USD")
    for evt in eth_events:
        print(f"  - {evt['title']}")

    print("\nXMR-USD events:")
    xmr_events = get_symbol_events(test_events, "XMR-USD")
    for evt in xmr_events:
        print(f"  - {evt['title']}")
