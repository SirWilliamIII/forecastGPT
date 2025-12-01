"use client";

import { HORIZONS } from "@/types/api";

interface HorizonSelectorProps {
  value: number;
  onChange: (horizon: number) => void;
}

export function HorizonSelector({ value, onChange }: HorizonSelectorProps) {
  return (
    <div className="flex gap-2">
      {HORIZONS.map((horizon) => {
        const isActive = value === horizon.value;

        return (
          <button
            key={horizon.value}
            onClick={() => onChange(horizon.value)}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
              isActive
                ? "bg-blue-600 text-white"
                : "text-gray-400 hover:bg-gray-800 hover:text-white"
            }`}
          >
            {horizon.label}
          </button>
        );
      })}
    </div>
  );
}
