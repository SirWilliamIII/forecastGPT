"use client";

import Link from "next/link";
import { formatDistanceToNow } from "@/lib/utils";
import type { EventSummary } from "@/types/api";

interface EventListProps {
  events: EventSummary[];
}

export function EventList({ events }: EventListProps) {
  if (events.length === 0) {
    return (
      <div className="rounded-xl border border-gray-700 bg-gray-800/50 p-8 text-center">
        <p className="text-gray-400">No events found</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {events.map((event) => (
        <EventCard key={event.id} event={event} />
      ))}
    </div>
  );
}

function EventCard({ event }: { event: EventSummary }) {
  return (
    <Link href={`/events/${event.id}`}>
      <div className="group rounded-xl border border-gray-700 bg-gray-800/50 p-4 transition-colors hover:border-blue-500/50 hover:bg-gray-800">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <h3 className="truncate font-medium text-white group-hover:text-blue-400">
              {event.title}
            </h3>
            <p className="mt-1 line-clamp-2 text-sm text-gray-400">
              {event.summary}
            </p>
          </div>
          <div className="flex-shrink-0 text-right">
            <p className="text-xs text-gray-500">
              {formatDistanceToNow(new Date(event.timestamp))}
            </p>
            <p className="mt-1 text-xs text-gray-600">{event.source}</p>
          </div>
        </div>

        {event.tags.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1">
            {event.tags.slice(0, 3).map((tag) => (
              <span
                key={tag}
                className="rounded-full bg-gray-700 px-2 py-0.5 text-xs text-gray-300"
              >
                {tag}
              </span>
            ))}
            {event.tags.length > 3 && (
              <span className="text-xs text-gray-500">
                +{event.tags.length - 3} more
              </span>
            )}
          </div>
        )}
      </div>
    </Link>
  );
}
