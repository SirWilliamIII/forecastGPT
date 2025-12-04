"use client";

interface SymbolSelectorProps {
  value: string;
  onChange: (symbol: string) => void;
  availableSymbols?: string[];
}

// Default symbol info with common crypto/equity patterns
function getSymbolInfo(symbol: string): { name: string; color: string } {
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
    };
  }

  // Equity patterns
  if (symbol.match(/^[A-Z]{1,5}$/)) {
    return {
      name: symbol,
      color: "bg-emerald-500",
    };
  }

  // Default
  return {
    name: symbol,
    color: "bg-gray-500",
  };
}

export function SymbolSelector({ value, onChange, availableSymbols = [] }: SymbolSelectorProps) {
  const symbols = availableSymbols.length > 0 ? availableSymbols : [value];

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
