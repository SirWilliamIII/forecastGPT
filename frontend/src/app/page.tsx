"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw, Activity, Newspaper } from "lucide-react";
import { ForecastCard } from "@/components/ForecastCard";
import { SymbolSelector } from "@/components/SymbolSelector";
import { HorizonSelector } from "@/components/HorizonSelector";
import { EventList } from "@/components/EventList";
import { getAssetForecast, getRecentEvents, getHealth } from "@/lib/api";
import type { Symbol } from "@/types/api";

export default function Dashboard() {
  const [symbol, setSymbol] = useState<Symbol>("BTC-USD");
  const [horizon, setHorizon] = useState(1440);

  const {
    data: forecast,
    isLoading: forecastLoading,
    refetch: refetchForecast,
  } = useQuery({
    queryKey: ["forecast", symbol, horizon],
    queryFn: () => getAssetForecast(symbol, horizon),
  });

  const { data: events, isLoading: eventsLoading } = useQuery({
    queryKey: ["events"],
    queryFn: () => getRecentEvents(10),
  });

  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
    refetchInterval: 30000,
  });

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Market Dashboard</h1>
          <p className="mt-1 text-gray-400">
            AI-powered forecasts conditioned on semantic events
          </p>
        </div>
        <div className="flex items-center gap-4">
          {health && (
            <div className="flex items-center gap-2">
              <span
                className={`h-2 w-2 rounded-full ${
                  health.status === "healthy" ? "bg-green-500" : "bg-red-500"
                }`}
              />
              <span className="text-sm text-gray-400">
                {health.status === "healthy" ? "Connected" : "Disconnected"}
              </span>
            </div>
          )}
          <button
            onClick={() => refetchForecast()}
            className="flex items-center gap-2 rounded-lg bg-gray-800 px-4 py-2 text-sm transition-colors hover:bg-gray-700"
          >
            <RefreshCw className="h-4 w-4" />
            Refresh
          </button>
        </div>
      </div>

      {/* Controls */}
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-gray-800 bg-gray-900/50 p-4">
        <div className="flex items-center gap-4">
          <span className="text-sm text-gray-400">Asset:</span>
          <SymbolSelector value={symbol} onChange={setSymbol} />
        </div>
        <div className="flex items-center gap-4">
          <span className="text-sm text-gray-400">Horizon:</span>
          <HorizonSelector value={horizon} onChange={setHorizon} />
        </div>
      </div>

      {/* Main Grid */}
      <div className="grid gap-8 lg:grid-cols-3">
        {/* Forecast Section */}
        <div className="lg:col-span-2 space-y-6">
          <div className="flex items-center gap-2">
            <Activity className="h-5 w-5 text-blue-500" />
            <h2 className="text-xl font-semibold">Forecast</h2>
          </div>

          {forecastLoading ? (
            <div className="animate-pulse rounded-xl border border-gray-700 bg-gray-800/50 p-6">
              <div className="h-20 rounded bg-gray-700" />
            </div>
          ) : forecast ? (
            <ForecastCard
              forecast={forecast}
              title={`${symbol} Baseline Forecast`}
            />
          ) : (
            <div className="rounded-xl border border-gray-700 bg-gray-800/50 p-6 text-center text-gray-400">
              No forecast data available
            </div>
          )}

          {/* Features Preview */}
          {forecast?.features && (
            <div className="rounded-xl border border-gray-700 bg-gray-800/50 p-4">
              <h3 className="mb-3 text-sm font-medium text-gray-400">
                Feature Snapshot
              </h3>
              <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
                {Object.entries(forecast.features)
                  .filter(
                    ([key]) =>
                      key.startsWith("price_r_") || key.startsWith("price_vol_")
                  )
                  .slice(0, 8)
                  .map(([key, value]) => (
                    <div key={key} className="rounded bg-gray-900 p-2">
                      <p className="text-xs text-gray-500">
                        {key.replace("price_", "")}
                      </p>
                      <p className="font-mono">
                        {typeof value === "number"
                          ? `${(value * 100).toFixed(2)}%`
                          : "—"}
                      </p>
                    </div>
                  ))}
              </div>
            </div>
          )}
        </div>

        {/* Events Sidebar */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Newspaper className="h-5 w-5 text-blue-500" />
              <h2 className="text-xl font-semibold">Recent Events</h2>
            </div>
            <a
              href="/events"
              className="text-sm text-blue-400 hover:text-blue-300"
            >
              View all →
            </a>
          </div>

          {eventsLoading ? (
            <div className="space-y-3">
              {[...Array(3)].map((_, i) => (
                <div
                  key={i}
                  className="animate-pulse rounded-xl border border-gray-700 bg-gray-800/50 p-4"
                >
                  <div className="h-12 rounded bg-gray-700" />
                </div>
              ))}
            </div>
          ) : events ? (
            <EventList events={events} />
          ) : null}
        </div>
      </div>
    </div>
  );
}
