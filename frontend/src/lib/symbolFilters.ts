// frontend/src/lib/symbolFilters.ts
/**
 * Client-side symbol filtering utilities
 * Mirrors backend logic from backend/signals/crypto_features.py
 */

import type { EventSummary } from "@/types/api";

/**
 * Symbol mention patterns (case-insensitive regex)
 * Must stay in sync with backend/signals/crypto_features.py
 */
const CRYPTO_SYMBOL_PATTERNS: Record<string, RegExp[]> = {
  "BTC-USD": [
    /\bBTC\b/i,
    /\bBitcoin\b/i,
    /\bBTC-USD\b/i,
    /\bXBT\b/i, // Alternative ticker
  ],
  "ETH-USD": [
    /\bETH\b/i,
    /\bEthereum\b/i,
    /\bETH-USD\b/i,
    /\bEther\b/i,
  ],
  "XMR-USD": [
    /\bXMR\b/i,
    /\bMonero\b/i,
    /\bXMR-USD\b/i,
  ],
};

/**
 * Check if event text mentions a specific crypto symbol
 */
export function isSymbolMentioned(eventText: string, symbol: string): boolean {
  const patterns = CRYPTO_SYMBOL_PATTERNS[symbol];

  if (!patterns) {
    // If no patterns defined for this symbol, include it (fallback to semantic similarity)
    return true;
  }

  // Check if any pattern matches
  for (const pattern of patterns) {
    if (pattern.test(eventText)) {
      return true;
    }
  }

  return false;
}

/**
 * Filter events to only those relevant to a specific symbol
 */
export function filterEventsBySymbol(
  events: EventSummary[],
  symbol: string
): EventSummary[] {
  return events.filter((event) => {
    // Combine title and summary for matching
    const textToCheck = `${event.title} ${event.summary || ""}`;
    return isSymbolMentioned(textToCheck, symbol);
  });
}

/**
 * Get symbol display info for badges and styling
 */
export function getSymbolInfo(symbol: string): {
  color: string;
  bgColor: string;
  borderColor: string;
  label: string;
} {
  switch (symbol) {
    case "BTC-USD":
      return {
        color: "text-orange-400",
        bgColor: "bg-orange-500/20",
        borderColor: "border-orange-500/30",
        label: "BTC",
      };
    case "ETH-USD":
      return {
        color: "text-blue-400",
        bgColor: "bg-blue-500/20",
        borderColor: "border-blue-500/30",
        label: "ETH",
      };
    case "XMR-USD":
      return {
        color: "text-purple-400",
        bgColor: "bg-purple-500/20",
        borderColor: "border-purple-500/30",
        label: "XMR",
      };
    default:
      return {
        color: "text-gray-400",
        bgColor: "bg-gray-500/20",
        borderColor: "border-gray-500/30",
        label: symbol,
      };
  }
}

/**
 * Detect which symbols are mentioned in an event
 * Used for multi-symbol badges
 */
export function detectMentionedSymbols(eventText: string): string[] {
  const mentioned: string[] = [];

  for (const symbol of Object.keys(CRYPTO_SYMBOL_PATTERNS)) {
    if (isSymbolMentioned(eventText, symbol)) {
      mentioned.push(symbol);
    }
  }

  return mentioned;
}
