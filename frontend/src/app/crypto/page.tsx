"use client";

import { useState, useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  RefreshCw,
  TrendingUp,
  Newspaper,
  ArrowRight,
} from "lucide-react";
import { ForecastCard } from "@/components/ForecastCard";
import { SymbolSelector } from "@/components/SymbolSelector";
import { HorizonSelector } from "@/components/HorizonSelector";
import { EventList } from "@/components/EventList";
import {
  getAssetForecast,
  getRecentEvents,
  getAvailableSymbols,
  getAvailableHorizons,
  type AvailableHorizon,
} from "@/lib/api";
import { filterEventsBySymbol, getSymbolInfo } from "@/lib/symbolFilters";

export default function CryptoPage() {
  const [symbol, setSymbol] = useState<string>("BTC-USD");
  const [availableSymbols, setAvailableSymbols] = useState<string[]>([]);
  const [horizon, setHorizon] = useState(1440);
  const [availableHorizons, setAvailableHorizons] = useState<AvailableHorizon[]>([]);

  const {
    data: forecast,
    isLoading: forecastLoading,
    refetch: refetchForecast,
  } = useQuery({
    queryKey: ["forecast", symbol, horizon],
    queryFn: () => getAssetForecast(symbol, horizon),
    staleTime: 2 * 60 * 1000,
    gcTime: 15 * 60 * 1000,
  });

  const {
    data: events,
    isLoading: eventsLoading,
    refetch: refetchEvents,
  } = useQuery({
    queryKey: ["events", "crypto"],
    queryFn: () => getRecentEvents(15, undefined, "crypto"),
    staleTime: 3 * 60 * 1000,
    gcTime: 20 * 60 * 1000,
  });

  const { data: symbolsData } = useQuery({
    queryKey: ["available-symbols"],
    queryFn: getAvailableSymbols,
    staleTime: 60 * 60 * 1000,
    gcTime: 24 * 60 * 60 * 1000,
  });

  const { data: horizonsData } = useQuery({
    queryKey: ["available-horizons"],
    queryFn: getAvailableHorizons,
    staleTime: 60 * 60 * 1000,
    gcTime: 24 * 60 * 60 * 1000,
  });

  useEffect(() => {
    if (symbolsData && symbolsData.crypto.length > 0) {
      setAvailableSymbols(symbolsData.crypto);
      if (symbol && !symbolsData.crypto.includes(symbol)) {
        setSymbol(symbolsData.crypto[0]);
      }
    }
  }, [symbolsData, symbol]);

  useEffect(() => {
    if (horizonsData && horizonsData.length > 0) {
      setAvailableHorizons(horizonsData);
      const availableValues = horizonsData.map(h => h.value);
      if (horizon && !availableValues.includes(horizon)) {
        setHorizon(horizonsData[0].value);
      }
    }
  }, [horizonsData, horizon]);

  // Filter events by selected symbol
  const filteredEvents = useMemo(() => {
    if (!events) return [];
    return filterEventsBySymbol(events, symbol);
  }, [events, symbol]);

  // Get symbol styling info
  const symbolInfo = useMemo(() => getSymbolInfo(symbol), [symbol]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <header className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">Crypto Forecasts</h1>
            <p className="mt-1 text-gray-400">
              ML-powered cryptocurrency return predictions
            </p>
          </div>
        </div>
      </header>

      {/* Main Grid */}
      <div className="grid gap-8 xl:grid-cols-3">
        {/* Left Column: Forecast */}
        <div className="space-y-6 xl:col-span-2">
          <section className="space-y-4">
            <div className="flex items-start justify-between gap-4 rounded-lg border border-orange-500/30 bg-orange-500/10 p-3">
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-orange-500/20">
                  <TrendingUp className="h-5 w-5 text-orange-400" />
                </div>
                <div>
                  <h2 className="text-lg font-semibold">Baseline Forecast</h2>
                  <p className="text-xs text-gray-500">
                    Historical pattern-based predictions
                  </p>
                </div>
              </div>
              <button
                onClick={() => refetchForecast()}
                className="flex items-center gap-1.5 rounded-lg bg-gray-800 px-3 py-1.5 text-xs transition-colors hover:bg-gray-700"
              >
                <RefreshCw className="h-3 w-3" />
                Refresh
              </button>
            </div>

            {/* Selectors */}
            <div className="flex flex-wrap items-center gap-4 rounded-lg border border-gray-800 bg-gray-900/40 p-3">
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-500">Target:</span>
                <SymbolSelector
                  value={symbol}
                  onChange={setSymbol}
                  availableSymbols={availableSymbols}
                />
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-500">Horizon:</span>
                <HorizonSelector
                  value={horizon}
                  onChange={setHorizon}
                  availableHorizons={availableHorizons}
                />
              </div>
            </div>

            {/* Forecast Card */}
            {forecastLoading ? (
              <div className="animate-pulse rounded-xl border border-gray-700 bg-gray-800/50 p-6">
                <div className="h-20 rounded bg-gray-700" />
              </div>
            ) : forecast ? (
              <ForecastCard forecast={forecast} title={`${symbol} Forecast`} />
            ) : (
              <div className="rounded-xl border border-gray-700 bg-gray-800/50 p-6 text-center text-gray-400">
                No forecast data available
              </div>
            )}

            {/* Feature Context */}
            {forecast?.features &&
              Object.keys(forecast.features).length > 0 && (
                <details className="rounded-lg border border-gray-800 bg-gray-900/30">
                  <summary className="cursor-pointer p-3 text-sm text-gray-400 hover:text-gray-200">
                    View feature context →
                  </summary>
                  <div className="grid grid-cols-2 gap-2 p-3 pt-0 text-xs md:grid-cols-4">
                    {Object.entries(forecast.features)
                      .slice(0, 8)
                      .map(([key, value]) => (
                        <div key={key} className="rounded bg-gray-900 p-2">
                          <p className="text-gray-500">{key}</p>
                          <p className="font-mono">
                            {typeof value === "number"
                              ? value.toFixed(4)
                              : "—"}
                          </p>
                        </div>
                      ))}
                  </div>
                </details>
              )}
          </section>
        </div>

        {/* Right Column: Events */}
        <aside className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Newspaper className="h-4 w-4 text-blue-400" />
              <h2 className="font-semibold">{symbolInfo.label} Events</h2>
            </div>
            <a
              href="/events"
              className="flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300"
            >
              All events <ArrowRight className="h-3 w-3" />
            </a>
          </div>

          <div className={`rounded-lg border ${symbolInfo.borderColor} p-3`} style={{ backgroundColor: symbolInfo.bgColor.replace('/20', '/5') }}>
            <div className="flex items-center justify-between gap-2">
              <p className="text-xs text-gray-400">
                Showing events mentioning <span className={`font-semibold ${symbolInfo.color}`}>{symbolInfo.label}</span>
              </p>
              {events && events.length > 0 && (
                <span className="text-xs text-gray-500">
                  {filteredEvents.length}/{events.length}
                </span>
              )}
            </div>
          </div>

          <button
            onClick={() => refetchEvents()}
            className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-gray-800 px-3 py-1.5 text-xs transition-colors hover:bg-gray-700"
          >
            <RefreshCw className="h-3 w-3" />
            Refresh Events
          </button>

          {eventsLoading ? (
            <div className="space-y-2">
              {[...Array(5)].map((_, i) => (
                <div
                  key={i}
                  className="animate-pulse rounded-lg border border-gray-700 bg-gray-800/50 p-3"
                >
                  <div className="h-12 rounded bg-gray-700" />
                </div>
              ))}
            </div>
          ) : filteredEvents && filteredEvents.length > 0 ? (
            <EventList events={filteredEvents} showSymbolBadges={true} />
          ) : events && events.length > 0 ? (
            <div className="rounded-lg border border-gray-700 bg-gray-800/50 p-4 text-center text-sm text-gray-500">
              No {symbolInfo.label}-specific events found.
              <p className="mt-1 text-xs">
                {events.length} crypto events available, none mention {symbolInfo.label}.
              </p>
            </div>
          ) : (
            <div className="rounded-lg border border-gray-700 bg-gray-800/50 p-4 text-center text-sm text-gray-500">
              No crypto events found.
              <p className="mt-1 text-xs">Run ingestion to populate.</p>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
