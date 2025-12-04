"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Newspaper, Filter } from "lucide-react";
import { EventList } from "@/components/EventList";
import { getRecentEvents } from "@/lib/api";

const SOURCES = [
  { value: "", label: "All Sources" },
  { value: "wired_ai", label: "Wired AI" },
  { value: "coindesk", label: "CoinDesk" },
];

export default function EventsPage() {
  const [source, setSource] = useState("");
  const [limit, setLimit] = useState(50);

  const { data: events, isLoading } = useQuery({
    queryKey: ["events", source, limit],
    queryFn: () => getRecentEvents(limit, source || undefined),
    staleTime: 3 * 60 * 1000, // 3 minutes
    gcTime: 20 * 60 * 1000, // Keep in cache for 20 minutes
  });

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h1 className="flex items-center gap-3 text-3xl font-bold">
          <Newspaper className="h-8 w-8 text-blue-500" />
          Event Feed
        </h1>
        <p className="mt-1 text-gray-400">
          Browse and analyze market-moving events
        </p>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-4 rounded-xl border border-gray-800 bg-gray-900/50 p-4">
        <div className="flex items-center gap-2">
          <Filter className="h-4 w-4 text-gray-400" />
          <span className="text-sm text-gray-400">Filter:</span>
        </div>

        <select
          value={source}
          onChange={(e) => setSource(e.target.value)}
          className="rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
        >
          {SOURCES.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>

        <select
          value={limit}
          onChange={(e) => setLimit(Number(e.target.value))}
          className="rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
        >
          <option value={25}>25 events</option>
          <option value={50}>50 events</option>
          <option value={100}>100 events</option>
        </select>

        {events && (
          <span className="ml-auto text-sm text-gray-500">
            Showing {events.length} events
          </span>
        )}
      </div>

      {/* Event List */}
      {isLoading ? (
        <div className="space-y-3">
          {[...Array(5)].map((_, i) => (
            <div
              key={i}
              className="animate-pulse rounded-xl border border-gray-700 bg-gray-800/50 p-4"
            >
              <div className="h-16 rounded bg-gray-700" />
            </div>
          ))}
        </div>
      ) : events ? (
        <EventList events={events} />
      ) : (
        <div className="rounded-xl border border-gray-700 bg-gray-800/50 p-8 text-center">
          <p className="text-gray-400">Failed to load events</p>
        </div>
      )}
    </div>
  );
}
