"use client";

import { SYMBOLS, type Symbol } from "@/types/api";

interface SymbolSelectorProps {
  value: Symbol;
  onChange: (symbol: Symbol) => void;
}

const SYMBOL_INFO: Record<Symbol, { name: string; color: string }> = {
  "BTC-USD": { name: "Bitcoin", color: "bg-orange-500" },
  "ETH-USD": { name: "Ethereum", color: "bg-blue-500" },
  "XMR-USD": { name: "Monero", color: "bg-gray-500" },
};

export function SymbolSelector({ value, onChange }: SymbolSelectorProps) {
  return (
    <div className="flex gap-2">
      {SYMBOLS.map((symbol) => {
        const info = SYMBOL_INFO[symbol];
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
            <span>{symbol.replace("-USD", "")}</span>
          </button>
        );
      })}
    </div>
  );
}
