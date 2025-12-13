"use client";

interface HorizonSelectorProps {
  value: number;
  onChange: (horizon: number) => void;
  availableHorizons?: Array<{ value: number; label: string; available: boolean }>;
}

// Fallback horizons if none provided
// Removed 1-day (1440 min) due to poor backtesting results (47.9% accuracy)
// Focused on validated horizons: 7d (60% accuracy), 30d (97.5% accuracy)
const DEFAULT_HORIZONS = [
  { value: 10080, label: "7 days", available: true },
  { value: 43200, label: "30 days", available: true },
];

// Get accuracy badge based on backtesting results
function getAccuracyBadge(horizonMinutes: number): { label: string; color: string } | null {
  if (horizonMinutes === 10080) return { label: "Good", color: "text-green-400" };
  if (horizonMinutes === 43200) return { label: "Best", color: "text-emerald-400" };
  return null;
}

// Get accuracy percentage for tooltip
function getAccuracyInfo(horizonMinutes: number): string | null {
  if (horizonMinutes === 10080) return "60% directional accuracy in backtesting";
  if (horizonMinutes === 43200) return "97.5% directional accuracy in backtesting (440 forecasts)";
  return null;
}

export function HorizonSelector({ value, onChange, availableHorizons = [] }: HorizonSelectorProps) {
  // Filter out 1-day horizon if present in availableHorizons
  const filteredHorizons = availableHorizons.length > 0
    ? availableHorizons.filter(h => h.value !== 1440)
    : DEFAULT_HORIZONS;

  const horizons = filteredHorizons.length > 0 ? filteredHorizons : DEFAULT_HORIZONS;

  return (
    <div className="flex gap-2">
      {horizons.map((horizon) => {
        const isActive = value === horizon.value;
        const isAvailable = horizon.available;
        const badge = getAccuracyBadge(horizon.value);
        const accuracyInfo = getAccuracyInfo(horizon.value);

        return (
          <button
            key={horizon.value}
            onClick={() => isAvailable && onChange(horizon.value)}
            disabled={!isAvailable}
            title={accuracyInfo || (!isAvailable ? "No training data for this horizon yet" : undefined)}
            className={`flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
              isActive
                ? "bg-blue-600 text-white"
                : isAvailable
                  ? "text-gray-400 hover:bg-gray-800 hover:text-white"
                  : "cursor-not-allowed text-gray-600 opacity-50"
            }`}
          >
            <span>{horizon.label}</span>
            {badge && (
              <span className={`text-xs font-semibold ${badge.color}`}>
                {badge.label}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
