"use client";

import { useMemo } from "react";
import {
  Newspaper,
  TrendingUp,
  TrendingDown,
  Activity,
  Calendar,
  Users,
} from "lucide-react";
import type { EventImpact } from "@/types/api";

interface EventImpactCardProps {
  impacts: EventImpact[] | undefined;
  isLoading: boolean;
  onEventClick?: (eventId: string) => void;
}

export function EventImpactCard({
  impacts,
  isLoading,
  onEventClick,
}: EventImpactCardProps) {
  // Sort by absolute impact (most significant first)
  const sortedImpacts = useMemo(() => {
    if (!impacts) return [];
    return [...impacts].sort(
      (a, b) => Math.abs(b.impact) - Math.abs(a.impact)
    );
  }, [impacts]);

  if (isLoading) {
    return (
      <div className="space-y-3 rounded-xl border border-gray-700 bg-gray-800/50 p-5">
        <div className="animate-pulse space-y-3">
          <div className="h-6 w-48 rounded bg-gray-700" />
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-20 rounded-lg bg-gray-700" />
          ))}
        </div>
      </div>
    );
  }

  if (!impacts || impacts.length === 0) {
    return (
      <div className="rounded-xl border border-gray-700 bg-gray-800/50 p-6 text-center">
        <Activity className="mx-auto h-12 w-12 text-gray-600" />
        <h3 className="mt-3 font-semibold text-gray-300">No event impacts yet</h3>
        <p className="mt-1 text-sm text-gray-500">
          Event impact data will appear as the forecasting system processes team
          news and events.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4 rounded-xl border border-gray-700 bg-gray-800/50 p-5">
      {/* Header */}
      <div className="flex items-center gap-2">
        <Newspaper className="h-5 w-5 text-orange-400" />
        <div>
          <h3 className="font-semibold text-gray-200">Recent Event Impacts</h3>
          <p className="text-xs text-gray-400">
            How news affects win probability
          </p>
        </div>
      </div>

      {/* Impact list */}
      <div className="space-y-2">
        {sortedImpacts.map((impact) => {
          const isPositive = impact.impact > 0;
          const isSignificant = Math.abs(impact.impact) >= 0.05; // 5% threshold
          const daysAgo = Math.floor(
            (Date.now() - new Date(impact.event_date).getTime()) /
              (1000 * 60 * 60 * 24)
          );

          return (
            <button
              key={impact.event_id}
              onClick={() => onEventClick?.(impact.event_id)}
              className="w-full rounded-lg border border-gray-700 bg-gray-800/50 p-4 text-left transition-all hover:border-gray-600 hover:bg-gray-800/70"
            >
              {/* Event title and date */}
              <div className="flex items-start gap-3">
                <div
                  className={`mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${
                    isPositive
                      ? "bg-green-500/20 text-green-400"
                      : "bg-red-500/20 text-red-400"
                  }`}
                >
                  {isPositive ? (
                    <TrendingUp className="h-4 w-4" />
                  ) : (
                    <TrendingDown className="h-4 w-4" />
                  )}
                </div>

                <div className="min-w-0 flex-1">
                  {/* Title */}
                  <p className="text-sm font-medium text-gray-200 line-clamp-2">
                    {impact.event_title}
                  </p>

                  {/* Metadata */}
                  <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-gray-400">
                    <div className="flex items-center gap-1">
                      <Calendar className="h-3 w-3" />
                      <span>
                        {daysAgo === 0
                          ? "Today"
                          : daysAgo === 1
                          ? "Yesterday"
                          : `${daysAgo}d ago`}
                      </span>
                    </div>
                    <div className="flex items-center gap-1">
                      <Users className="h-3 w-3" />
                      <span>{impact.similar_events_count} similar events</span>
                    </div>
                  </div>

                  {/* Impact details */}
                  <div className="mt-2 flex items-center gap-2">
                    <div className="flex items-baseline gap-1.5">
                      <span className="text-xs text-gray-500">Win prob:</span>
                      <span className="text-sm font-semibold text-gray-300">
                        {(impact.win_prob_before * 100).toFixed(1)}%
                      </span>
                      <span className="text-gray-500">→</span>
                      <span
                        className={`text-sm font-semibold ${
                          isPositive ? "text-green-400" : "text-red-400"
                        }`}
                      >
                        {(impact.win_prob_after * 100).toFixed(1)}%
                      </span>
                    </div>

                    <div
                      className={`ml-auto rounded px-2 py-0.5 text-xs font-semibold ${
                        isSignificant
                          ? isPositive
                            ? "bg-green-500/20 text-green-400"
                            : "bg-red-500/20 text-red-400"
                          : "bg-gray-700 text-gray-400"
                      }`}
                    >
                      {isPositive ? "+" : ""}
                      {(impact.impact * 100).toFixed(1)}%
                    </div>
                  </div>
                </div>
              </div>
            </button>
          );
        })}
      </div>

      {/* Footer note */}
      <div className="rounded-lg border border-blue-500/20 bg-blue-500/5 p-3 text-xs text-gray-400">
        <p>
          <span className="font-medium text-blue-400">How it works:</span> Each
          event is compared to similar historical events using semantic
          embeddings. The forecast shows how similar past events affected game
          outcomes.
        </p>
      </div>
    </div>
  );
}
