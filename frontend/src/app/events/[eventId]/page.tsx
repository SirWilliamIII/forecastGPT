"use client";

import { use, useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  ExternalLink,
  TrendingUp,
  Users,
  Calendar,
  Tag,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
import { ForecastComparisonCard } from "@/components/ForecastComparisonCard";
import { SymbolSelector } from "@/components/SymbolSelector";
import { HorizonSelector } from "@/components/HorizonSelector";
import { ConfidenceBadge } from "@/components/ConfidenceBadge";
import {
  getSimilarEvents,
  getEventForecast,
  getAssetForecast,
  getEventDetails,
  getAvailableSymbols,
  getAvailableHorizons,
  type AvailableHorizon,
} from "@/lib/api";
import { formatDistanceToNow } from "@/lib/utils";
import type { Symbol } from "@/types/api";

export default function EventDetailPage({
  params,
}: {
  params: Promise<{ eventId: string }>;
}) {
  const { eventId } = use(params);
  const [symbol, setSymbol] = useState<Symbol>("BTC-USD");
  const [horizon, setHorizon] = useState(1440);
  const [availableSymbols, setAvailableSymbols] = useState<string[]>([]);
  const [availableHorizons, setAvailableHorizons] = useState<AvailableHorizon[]>([]);

  // Fetch event details
  const { data: event, isLoading: eventLoading } = useQuery({
    queryKey: ["event", eventId],
    queryFn: () => getEventDetails(eventId),
    staleTime: 30 * 60 * 1000,
    gcTime: 60 * 60 * 1000,
  });

  // Fetch similar events
  const { data: similarEvents, isLoading: neighborsLoading } = useQuery({
    queryKey: ["similar", eventId],
    queryFn: () => getSimilarEvents(eventId, 10),
    staleTime: 30 * 60 * 1000,
    gcTime: 60 * 60 * 1000,
  });

  // Fetch event forecast
  const { data: eventForecast, isLoading: eventForecastLoading } = useQuery({
    queryKey: ["eventForecast", eventId, symbol, horizon],
    queryFn: () => getEventForecast(eventId, symbol, horizon),
    staleTime: 2 * 60 * 1000,
    gcTime: 15 * 60 * 1000,
  });

  // Fetch baseline forecast for comparison
  const { data: baselineForecast, isLoading: baselineLoading } = useQuery({
    queryKey: ["baseline", symbol, horizon],
    queryFn: () => getAssetForecast(symbol, horizon),
    staleTime: 2 * 60 * 1000,
    gcTime: 15 * 60 * 1000,
  });

  // Fetch available symbols and horizons
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

  // Update available symbols
  useMemo(() => {
    if (symbolsData && symbolsData.crypto.length > 0) {
      setAvailableSymbols(symbolsData.crypto);
    }
  }, [symbolsData]);

  // Update available horizons
  useMemo(() => {
    if (horizonsData && horizonsData.length > 0) {
      setAvailableHorizons(horizonsData);
    }
  }, [horizonsData]);

  return (
    <div className="space-y-6">
      {/* Back Button */}
      <Link
        href="/events"
        className="inline-flex items-center gap-2 text-sm text-gray-400 hover:text-white"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to Events
      </Link>

      {/* Event Details Card */}
      {eventLoading ? (
        <div className="animate-pulse rounded-xl border border-gray-700 bg-gray-800/50 p-6">
          <div className="h-32 rounded bg-gray-700" />
        </div>
      ) : event ? (
        <div className="rounded-xl border border-blue-500/30 bg-blue-500/5 p-6">
          <div className="space-y-4">
            {/* Title and Source */}
            <div>
              <div className="flex items-start justify-between gap-4">
                <h1 className="text-2xl font-bold text-white">{event.title}</h1>
                {event.url && (
                  <a
                    href={event.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1 text-sm text-blue-400 hover:text-blue-300"
                  >
                    <ExternalLink className="h-4 w-4" />
                    Source
                  </a>
                )}
              </div>
              <p className="mt-2 text-gray-300">{event.summary}</p>
            </div>

            {/* Metadata */}
            <div className="flex flex-wrap items-center gap-4 border-t border-blue-500/20 pt-4 text-sm">
              <div className="flex items-center gap-2">
                <Calendar className="h-4 w-4 text-gray-500" />
                <span className="text-gray-400">
                  {formatDistanceToNow(new Date(event.timestamp))}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-gray-500" />
                <span className="text-gray-400">{event.source}</span>
              </div>
            </div>

            {/* Tags */}
            {event.tags.length > 0 && (
              <div className="flex flex-wrap items-center gap-2 border-t border-blue-500/20 pt-4">
                <Tag className="h-4 w-4 text-gray-500" />
                {event.tags.map((tag) => (
                  <span
                    key={tag}
                    className="rounded-full border border-blue-500/30 bg-blue-500/10 px-3 py-1 text-xs text-blue-300"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            )}

            {/* Categories */}
            {event.categories.length > 0 && (
              <div className="flex flex-wrap items-center gap-2">
                {event.categories.map((category) => (
                  <span
                    key={category}
                    className="rounded border border-gray-600 bg-gray-700 px-2 py-0.5 text-xs text-gray-300"
                  >
                    {category}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className="rounded-xl border border-gray-700 bg-gray-800/50 p-6 text-center text-gray-400">
          Event not found. It may be too old or not yet indexed.
        </div>
      )}

      {/* Forecast Controls */}
      <div className="rounded-lg border border-gray-800 bg-gray-900/40 p-4">
        <h3 className="mb-3 text-sm font-semibold text-gray-300">
          Forecast Configuration
        </h3>
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-500">Target:</span>
            <SymbolSelector
              value={symbol}
              onChange={(s) => setSymbol(s as Symbol)}
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
      </div>

      {/* Forecast Comparison */}
      {baselineForecast && (
        <ForecastComparisonCard
          symbol={symbol}
          horizonMinutes={horizon}
          baselineForecast={baselineForecast}
          eventForecast={eventForecast}
          eventTitle={event?.title}
        />
      )}

      {/* Similar Events Section */}
      <div className="rounded-xl border border-gray-700 bg-gray-800/50 p-6">
        <h2 className="mb-4 flex items-center gap-2 text-xl font-semibold">
          <Users className="h-5 w-5 text-blue-400" />
          Semantic Neighbors
        </h2>
        <p className="mb-6 text-sm text-gray-400">
          Events with similar embeddings from the past. The forecast above is
          based on outcomes after these similar events.
        </p>

        {neighborsLoading ? (
          <div className="space-y-3">
            {[...Array(5)].map((_, i) => (
              <div
                key={i}
                className="animate-pulse rounded-lg border border-gray-700 bg-gray-800/50 p-4"
              >
                <div className="h-16 rounded bg-gray-700" />
              </div>
            ))}
          </div>
        ) : similarEvents?.neighbors.length ? (
          <div className="space-y-3">
            {similarEvents.neighbors.map((neighbor, idx) => {
              // Calculate similarity percentage (lower distance = higher similarity)
              const similarity = Math.max(0, (1 - neighbor.distance) * 100);

              return (
                <div
                  key={neighbor.id}
                  className="group rounded-lg border border-gray-700 bg-gray-900/50 p-4 transition-colors hover:border-blue-500/50"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1">
                      {/* Rank and Similarity */}
                      <div className="mb-2 flex items-center gap-2">
                        <span className="rounded bg-blue-500/20 px-2 py-0.5 text-xs font-semibold text-blue-300">
                          #{idx + 1}
                        </span>
                        <div className="flex items-center gap-2">
                          <div className="h-1.5 w-24 overflow-hidden rounded-full bg-gray-700">
                            <div
                              className="h-full bg-blue-500"
                              style={{ width: `${similarity}%` }}
                            />
                          </div>
                          <span className="text-xs text-gray-500">
                            {similarity.toFixed(1)}% similar
                          </span>
                        </div>
                      </div>

                      {/* Event Text */}
                      <p className="text-sm leading-relaxed text-gray-300">
                        {neighbor.raw_text.slice(0, 250)}
                        {neighbor.raw_text.length > 250 && "..."}
                      </p>

                      {/* Tags */}
                      {neighbor.tags.length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-1">
                          {neighbor.tags.slice(0, 4).map((tag) => (
                            <span
                              key={tag}
                              className="rounded-full bg-gray-700 px-2 py-0.5 text-xs text-gray-400"
                            >
                              {tag}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>

                    {/* Metadata */}
                    <div className="flex-shrink-0 text-right text-xs text-gray-500">
                      <p className="font-medium">{neighbor.source}</p>
                      {neighbor.timestamp && (
                        <p className="mt-1">
                          {formatDistanceToNow(new Date(neighbor.timestamp))}
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="rounded-lg border border-gray-700 bg-gray-800/50 p-6 text-center text-gray-400">
            No similar events found
          </div>
        )}

        {/* Explanation */}
        {eventForecast && similarEvents?.neighbors.length && (
          <div className="mt-6 rounded-lg border border-blue-500/30 bg-blue-500/5 p-4">
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-blue-300">
              <TrendingUp className="h-4 w-4" />
              How This Works
            </h3>
            <p className="text-xs leading-relaxed text-gray-400">
              The event-conditioned forecast analyzes {eventForecast.sample_size}{" "}
              historical events with similar semantic content. We weight each
              neighbor&apos;s outcome by similarity and aggregate to predict how{" "}
              {symbol.split("-")[0]} will likely respond to this event over the
              next {horizon >= 1440 ? `${horizon / 1440} day(s)` : `${horizon / 60} hour(s)`}.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
