"use client";

import { TrendingUp, TrendingDown, Minus, AlertCircle } from "lucide-react";
import type { AssetForecast } from "@/types/api";

interface ForecastCardProps {
  forecast: AssetForecast;
  title?: string;
}

export function ForecastCard({ forecast, title }: ForecastCardProps) {
  const { expected_return, direction, confidence, n_points, vol_return } =
    forecast;

  const formatPercent = (value: number | null) => {
    if (value === null) return "—";
    return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(2)}%`;
  };

  const getDirectionIcon = () => {
    if (direction === "up")
      return <TrendingUp className="h-6 w-6 text-green-500" />;
    if (direction === "down")
      return <TrendingDown className="h-6 w-6 text-red-500" />;
    return <Minus className="h-6 w-6 text-gray-400" />;
  };

  const getDirectionColor = () => {
    if (direction === "up") return "text-green-500";
    if (direction === "down") return "text-red-500";
    return "text-gray-400";
  };

  const isLowConfidence = n_points < 10;

  return (
    <div className="rounded-xl border border-gray-700 bg-gray-800/50 p-6">
      {title && (
        <h3 className="mb-4 text-sm font-medium text-gray-400">{title}</h3>
      )}

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {getDirectionIcon()}
          <div>
            <p className={`text-2xl font-bold ${getDirectionColor()}`}>
              {formatPercent(expected_return)}
            </p>
            <p className="text-sm text-gray-400">
              {forecast.horizon_minutes / 60}h forecast
            </p>
          </div>
        </div>

        <div className="text-right">
          <p className="text-sm text-gray-400">Confidence</p>
          <div className="flex items-center gap-2">
            <div className="h-2 w-20 overflow-hidden rounded-full bg-gray-700">
              <div
                className="h-full bg-blue-500 transition-all"
                style={{ width: `${confidence * 100}%` }}
              />
            </div>
            <span className="text-sm font-medium">
              {(confidence * 100).toFixed(0)}%
            </span>
          </div>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-4 border-t border-gray-700 pt-4">
        <div>
          <p className="text-xs text-gray-500">Volatility</p>
          <p className="font-mono text-sm">{formatPercent(vol_return)}</p>
        </div>
        <div>
          <p className="text-xs text-gray-500">Data Points</p>
          <div className="flex items-center gap-1">
            <p className="font-mono text-sm">{n_points}</p>
            {isLowConfidence && (
              <AlertCircle className="h-3 w-3 text-yellow-500" />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
