"use client";

interface SymbolSelectorProps {
  value: string;
  onChange: (symbol: string) => void;
  availableSymbols?: string[];
}

// Default symbol info with common crypto/equity patterns
// Note: Equity symbols (NVDA, etc.) removed from forecasting due to poor backtesting results
// (31.6% accuracy vs 61-66% for crypto). Different market dynamics (trading hours, gaps)
// require equity-specific models.
function getSymbolInfo(symbol: string): { name: string; color: string; isEquity?: boolean } {
  // Crypto patterns
  if (symbol.includes("-USD")) {
    const asset = symbol.replace("-USD", "");
    const colors: Record<string, string> = {
      BTC: "bg-orange-500",
      ETH: "bg-purple-500",
      XMR: "bg-gray-500",
      SOL: "bg-cyan-500",
      AVAX: "bg-red-500",
    };
    return {
      name: asset,
      color: colors[asset] || "bg-blue-500",
      isEquity: false,
    };
  }

  // Equity patterns (currently excluded from crypto forecasting)
  if (symbol.match(/^[A-Z]{1,5}$/)) {
    return {
      name: symbol,
      color: "bg-emerald-500",
      isEquity: true,
    };
  }

  // Default
  return {
    name: symbol,
    color: "bg-gray-500",
  };
}

export function SymbolSelector({ value, onChange, availableSymbols = [] }: SymbolSelectorProps) {
  // Filter out equity symbols due to poor backtesting results (31.6% accuracy)
  // Only show crypto symbols which have validated 61-66% accuracy
  const filteredSymbols = availableSymbols.length > 0
    ? availableSymbols.filter(s => !getSymbolInfo(s).isEquity)
    : [value];

  const symbols = filteredSymbols.length > 0 ? filteredSymbols : [value];

  return (
    <div className="flex gap-2">
      {symbols.map((symbol) => {
        const info = getSymbolInfo(symbol);
        const isActive = value === symbol;

        return (
          <button
            key={symbol}
            onClick={() => onChange(symbol)}
            className={`flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
              isActive
                ? "bg-gray-700 text-white"
                : "text-gray-400 hover:bg-gray-800 hover:text-white"
            }`}
          >
            <span className={`h-2 w-2 rounded-full ${info.color}`} />
            <span>{info.name}</span>
          </button>
        );
      })}
    </div>
  );
}
