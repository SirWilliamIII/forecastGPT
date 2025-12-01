"use client";

import { use } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  ExternalLink,
  TrendingUp,
  TrendingDown,
  Brain,
  Users,
} from "lucide-react";
import Link from "next/link";
import { ForecastCard } from "@/components/ForecastCard";
import { SymbolSelector } from "@/components/SymbolSelector";
import {
  getSimilarEvents,
  getEventForecast,
  getAssetForecast,
} from "@/lib/api";
import { formatDistanceToNow, formatPercent } from "@/lib/utils";
import type { Symbol } from "@/types/api";
import { useState } from "react";

export default function EventDetailPage({
  params,
}: {
  params: Promise<{ eventId: string }>;
}) {
  const { eventId } = use(params);
  const [symbol, setSymbol] = useState<Symbol>("BTC-USD");

  const { data: similarEvents, isLoading: neighborsLoading } = useQuery({
    queryKey: ["similar", eventId],
    queryFn: () => getSimilarEvents(eventId, 5),
  });

  const { data: eventForecast, isLoading: eventForecastLoading } = useQuery({
    queryKey: ["eventForecast", eventId, symbol],
    queryFn: () => getEventForecast(eventId, symbol),
  });

  const { data: baselineForecast } = useQuery({
    queryKey: ["baseline", symbol],
    queryFn: () => getAssetForecast(symbol),
  });

  return (
    <div className="space-y-8">
      {/* Back Button */}
      <Link
        href="/events"
        className="inline-flex items-center gap-2 text-sm text-gray-400 hover:text-white"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to Events
      </Link>

      {/* Event Header */}
      <div className="rounded-xl border border-gray-700 bg-gray-800/50 p-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-sm text-gray-500">Event ID</p>
            <p className="font-mono text-sm text-gray-300">{eventId}</p>
          </div>
        </div>
      </div>

      {/* Symbol Selector */}
      <div className="flex items-center gap-4">
        <span className="text-sm text-gray-400">Analyze for:</span>
        <SymbolSelector value={symbol} onChange={setSymbol} />
      </div>

      {/* Forecast Comparison */}
      <div className="grid gap-6 md:grid-cols-2">
        {/* Baseline Forecast */}
        <div>
          <h2 className="mb-4 flex items-center gap-2 text-lg font-semibold">
            <TrendingUp className="h-5 w-5 text-gray-400" />
            Baseline Forecast
          </h2>
          {baselineForecast ? (
            <ForecastCard forecast={baselineForecast} />
          ) : (
            <div className="animate-pulse rounded-xl border border-gray-700 bg-gray-800/50 p-6">
              <div className="h-20 rounded bg-gray-700" />
            </div>
          )}
        </div>

        {/* Event-Conditioned Forecast */}
        <div>
          <h2 className="mb-4 flex items-center gap-2 text-lg font-semibold">
            <Brain className="h-5 w-5 text-blue-500" />
            Event-Conditioned Forecast
          </h2>
          {eventForecastLoading ? (
            <div className="animate-pulse rounded-xl border border-gray-700 bg-gray-800/50 p-6">
              <div className="h-20 rounded bg-gray-700" />
            </div>
          ) : eventForecast ? (
            <div className="rounded-xl border border-gray-700 bg-gray-800/50 p-6">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  {eventForecast.expected_return > 0 ? (
                    <TrendingUp className="h-6 w-6 text-green-500" />
                  ) : (
                    <TrendingDown className="h-6 w-6 text-red-500" />
                  )}
                  <div>
                    <p
                      className={`text-2xl font-bold ${
                        eventForecast.expected_return > 0
                          ? "text-green-500"
                          : "text-red-500"
                      }`}
                    >
                      {formatPercent(eventForecast.expected_return)}
                    </p>
                    <p className="text-sm text-gray-400">
                      Based on {eventForecast.neighbors_used} similar events
                    </p>
                  </div>
                </div>

                <div className="text-right">
                  <p className="text-sm text-gray-400">Probability Up</p>
                  <p className="text-lg font-semibold">
                    {(eventForecast.p_up * 100).toFixed(0)}%
                  </p>
                </div>
              </div>

              <div className="mt-4 grid grid-cols-3 gap-4 border-t border-gray-700 pt-4 text-sm">
                <div>
                  <p className="text-gray-500">Std Dev</p>
                  <p className="font-mono">
                    {formatPercent(eventForecast.std_return)}
                  </p>
                </div>
                <div>
                  <p className="text-gray-500">Sample Size</p>
                  <p className="font-mono">{eventForecast.sample_size}</p>
                </div>
                <div>
                  <p className="text-gray-500">Horizon</p>
                  <p className="font-mono">
                    {eventForecast.horizon_minutes / 60}h
                  </p>
                </div>
              </div>
            </div>
          ) : (
            <div className="rounded-xl border border-gray-700 bg-gray-800/50 p-6 text-center text-gray-400">
              No forecast data available
            </div>
          )}
        </div>
      </div>

      {/* Similar Events */}
      <div>
        <h2 className="mb-4 flex items-center gap-2 text-lg font-semibold">
          <Users className="h-5 w-5 text-blue-500" />
          Semantically Similar Events
        </h2>

        {neighborsLoading ? (
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
        ) : similarEvents?.neighbors.length ? (
          <div className="space-y-3">
            {similarEvents.neighbors.map((neighbor, idx) => (
              <div
                key={neighbor.id}
                className="rounded-xl border border-gray-700 bg-gray-800/50 p-4"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span className="rounded bg-gray-700 px-2 py-0.5 text-xs text-gray-300">
                        #{idx + 1}
                      </span>
                      <span className="text-xs text-gray-500">
                        Distance: {neighbor.distance.toFixed(4)}
                      </span>
                    </div>
                    <p className="mt-2 text-sm text-gray-300">
                      {neighbor.raw_text.slice(0, 200)}
                      {neighbor.raw_text.length > 200 && "..."}
                    </p>
                  </div>
                  <div className="text-right text-xs text-gray-500">
                    <p>{neighbor.source}</p>
                    {neighbor.timestamp && (
                      <p>{formatDistanceToNow(new Date(neighbor.timestamp))}</p>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="rounded-xl border border-gray-700 bg-gray-800/50 p-6 text-center text-gray-400">
            No similar events found
          </div>
        )}
      </div>
    </div>
  );
}
