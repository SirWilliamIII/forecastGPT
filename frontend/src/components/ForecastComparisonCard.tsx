"use client";

import { TrendingUp, TrendingDown, ArrowRight, Sparkles } from "lucide-react";
import type { AssetForecast, EventReturnForecast } from "@/types/api";
import { ConfidenceBadge, ConfidenceIndicator } from "./ConfidenceBadge";
import { RegimeBadge } from "./RegimeBadge";

interface ForecastComparisonCardProps {
  symbol: string;
  horizonMinutes: number;
  baselineForecast: AssetForecast;
  eventForecast?: EventReturnForecast;
  eventTitle?: string;
}

export function ForecastComparisonCard({
  symbol,
  horizonMinutes,
  baselineForecast,
  eventForecast,
  eventTitle,
}: ForecastComparisonCardProps) {
  const formatPercent = (value: number | null) => {
    if (value === null) return "—";
    return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(2)}%`;
  };

  const getDirectionIcon = (direction: string | null, returnValue?: number | null) => {
    // Binary classification only - "flat" predictions showed 0% accuracy in backtesting
    // Treat flat as up/down based on return value sign
    const effectiveDirection = direction === "flat"
      ? (returnValue && returnValue >= 0 ? "up" : "down")
      : direction;

    if (effectiveDirection === "up") return "↗";
    if (effectiveDirection === "down") return "↘";
    return "↗"; // Default to up
  };

  const getDirectionColor = (direction: string | null, returnValue?: number | null) => {
    // Binary classification only - "flat" predictions showed 0% accuracy in backtesting
    const effectiveDirection = direction === "flat"
      ? (returnValue && returnValue >= 0 ? "up" : "down")
      : direction;

    if (effectiveDirection === "up") return "text-green-400";
    if (effectiveDirection === "down") return "text-red-400";
    return "text-green-400"; // Default to up
  };

  // Calculate confidence bar width (0-100%)
  const getConfidenceWidth = (confidence: number) => {
    return Math.min(100, Math.max(0, confidence * 100));
  };

  const horizonLabel =
    horizonMinutes >= 1440
      ? `${horizonMinutes / 1440}d`
      : `${horizonMinutes / 60}h`;

  return (
    <div className="rounded-xl border border-gray-700 bg-gray-800/50 p-6">
      {/* Header */}
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold">
            {symbol} {horizonLabel} Forecast Comparison
          </h3>
          {eventTitle && (
            <p className="mt-1 text-xs text-gray-500">
              Event: {eventTitle.slice(0, 60)}
              {eventTitle.length > 60 ? "..." : ""}
            </p>
          )}
        </div>
        {baselineForecast.features?.regime ? (
          <RegimeBadge regime={baselineForecast.features.regime as string} />
        ) : null}
      </div>

      {/* Comparison Grid */}
      <div className="space-y-3">
        {/* Baseline Forecast */}
        <div className="rounded-lg border border-gray-700 bg-gray-900/50 p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-500/10">
                <TrendingUp className="h-5 w-5 text-blue-400" />
              </div>
              <div>
                <p className="text-xs text-gray-500">Baseline (Historical)</p>
                <div className="flex items-center gap-2">
                  <span
                    className={`text-xl font-bold ${getDirectionColor(baselineForecast.direction, baselineForecast.expected_return)}`}
                  >
                    {formatPercent(baselineForecast.expected_return)}
                  </span>
                  <span
                    className={`text-2xl ${getDirectionColor(baselineForecast.direction, baselineForecast.expected_return)}`}
                  >
                    {getDirectionIcon(baselineForecast.direction, baselineForecast.expected_return)}
                  </span>
                </div>
              </div>
            </div>
            <div className="text-right">
              <ConfidenceIndicator
                sampleSize={baselineForecast.n_points}
                confidence={baselineForecast.confidence}
              />
              <div className="mt-2 flex items-center gap-2">
                <div className="h-2 w-20 overflow-hidden rounded-full bg-gray-700">
                  <div
                    className="h-full bg-blue-500 transition-all"
                    style={{
                      width: `${getConfidenceWidth(baselineForecast.confidence)}%`,
                    }}
                  />
                </div>
                <span className="text-xs text-gray-500">
                  {(baselineForecast.confidence * 100).toFixed(0)}%
                </span>
              </div>
              <p className="mt-1 text-xs text-gray-600">
                {baselineForecast.n_points} samples
              </p>
            </div>
          </div>
        </div>

        {/* Event-Adjusted Forecast */}
        {eventForecast ? (
          <div className="rounded-lg border border-purple-500/30 bg-purple-500/5 p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-purple-500/10">
                  <Sparkles className="h-5 w-5 text-purple-400" />
                </div>
                <div>
                  <p className="text-xs text-gray-500">Event-Adjusted</p>
                  <div className="flex items-center gap-2">
                    <span
                      className={`text-xl font-bold ${eventForecast.expected_return >= 0 ? "text-green-400" : "text-red-400"}`}
                    >
                      {formatPercent(eventForecast.expected_return)}
                    </span>
                    <span
                      className={`text-2xl ${eventForecast.expected_return >= 0 ? "text-green-400" : "text-red-400"}`}
                    >
                      {eventForecast.expected_return >= 0 ? "↗" : "↘"}
                    </span>
                  </div>
                </div>
              </div>
              <div className="text-right">
                <ConfidenceIndicator
                  sampleSize={eventForecast.sample_size}
                  confidence={eventForecast.p_up}
                />
                <div className="mt-2 flex items-center gap-2">
                  <div className="h-2 w-20 overflow-hidden rounded-full bg-gray-700">
                    <div
                      className="h-full bg-purple-500 transition-all"
                      style={{
                        width: `${getConfidenceWidth(eventForecast.p_up)}%`,
                      }}
                    />
                  </div>
                  <span className="text-xs text-gray-500">
                    {(eventForecast.p_up * 100).toFixed(0)}%
                  </span>
                </div>
                <p className="mt-1 text-xs text-gray-600">
                  {eventForecast.sample_size} similar events
                </p>
              </div>
            </div>

            {/* Event Insight */}
            <div className="mt-3 rounded border border-purple-500/20 bg-purple-500/5 p-2">
              <p className="text-xs text-purple-300">
                <span className="font-semibold">Key Insight:</span> After{" "}
                {eventForecast.sample_size} similar events,{" "}
                {symbol.split("-")[0]} went{" "}
                {eventForecast.p_up > 0.5 ? "up" : "down"}{" "}
                {Math.max(eventForecast.p_up, eventForecast.p_down) * 100}% of
                the time
                {eventForecast.p_up > 0.5
                  ? ` (avg +${(eventForecast.expected_return * 100).toFixed(2)}%)`
                  : ` (avg ${(eventForecast.expected_return * 100).toFixed(2)}%)`}
              </p>
            </div>
          </div>
        ) : (
          <div className="rounded-lg border border-gray-700 bg-gray-900/30 p-4 text-center">
            <p className="text-sm text-gray-500">
              Select an event to see event-adjusted forecast
            </p>
          </div>
        )}
      </div>

      {/* Confidence Summary */}
      {eventForecast && (
        <div className="mt-4 border-t border-gray-700 pt-4">
          <ConfidenceBadge
            sampleSize={eventForecast.sample_size}
            confidence={eventForecast.p_up}
          />
        </div>
      )}
    </div>
  );
}
