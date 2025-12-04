"use client";

interface HorizonSelectorProps {
  value: number;
  onChange: (horizon: number) => void;
  availableHorizons?: Array<{ value: number; label: string; available: boolean }>;
}

// Fallback horizons if none provided
const DEFAULT_HORIZONS = [
  { value: 1440, label: "24 hours", available: true },
];

export function HorizonSelector({ value, onChange, availableHorizons = [] }: HorizonSelectorProps) {
  const horizons = availableHorizons.length > 0 ? availableHorizons : DEFAULT_HORIZONS;

  return (
    <div className="flex gap-2">
      {horizons.map((horizon) => {
        const isActive = value === horizon.value;
        const isAvailable = horizon.available;

        return (
          <button
            key={horizon.value}
            onClick={() => isAvailable && onChange(horizon.value)}
            disabled={!isAvailable}
            title={!isAvailable ? "No training data for this horizon yet" : undefined}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
              isActive
                ? "bg-blue-600 text-white"
                : isAvailable
                  ? "text-gray-400 hover:bg-gray-800 hover:text-white"
                  : "cursor-not-allowed text-gray-600 opacity-50"
            }`}
          >
            {horizon.label}
          </button>
        );
      })}
    </div>
  );
}
