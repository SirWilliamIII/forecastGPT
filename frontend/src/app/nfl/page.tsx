"use client";

import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  RefreshCw,
  Activity,
  Newspaper,
  ArrowRight,
} from "lucide-react";
import { EventList } from "@/components/EventList";
import { ProjectionCard } from "@/components/ProjectionCard";
import { NFLEventForecast } from "@/components/NFLEventForecast";
import {
  getRecentEvents,
  getLatestProjections,
  getProjectionTeams,
  getNFLTeamForecast,
} from "@/lib/api";

export default function NFLPage() {
  const [projectionSymbol, setProjectionSymbol] = useState<string>("NFL:DAL_COWBOYS");
  const [projectionTeams, setProjectionTeams] = useState<Record<string, string>>({});

  const {
    data: events,
    isLoading: eventsLoading,
    refetch: refetchEvents,
  } = useQuery({
    queryKey: ["events", "sports"],
    queryFn: () => getRecentEvents(15, undefined, "sports"),
    staleTime: 3 * 60 * 1000,
    gcTime: 20 * 60 * 1000,
  });

  const {
    data: projections,
    isLoading: projectionsLoading,
    refetch: refetchProjections,
  } = useQuery({
    queryKey: ["projections", projectionSymbol],
    queryFn: () => getLatestProjections(projectionSymbol, "win_prob", 10),
    staleTime: 5 * 60 * 1000,
    gcTime: 30 * 60 * 1000,
  });

  const { data: teamsData } = useQuery({
    queryKey: ["projection-teams"],
    queryFn: getProjectionTeams,
    staleTime: 60 * 60 * 1000,
    gcTime: 24 * 60 * 60 * 1000,
  });

  const {
    data: eventForecast,
    isLoading: forecastLoading,
    refetch: refetchForecast,
  } = useQuery({
    queryKey: ["nfl-event-forecast", projectionSymbol],
    queryFn: () => getNFLTeamForecast(projectionSymbol, true),
    staleTime: 5 * 60 * 1000,
    gcTime: 30 * 60 * 1000,
  });

  useEffect(() => {
    if (teamsData && Object.keys(teamsData).length > 0) {
      setProjectionTeams(teamsData);
      const teamValues = Object.values(teamsData);
      if (teamValues.length > 0 && !teamValues.includes(projectionSymbol)) {
        setProjectionSymbol(teamValues[0]);
      }
    }
  }, [teamsData, projectionSymbol]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <header className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">NFL Projections</h1>
            <p className="mt-1 text-gray-400">
              Win probabilities and game predictions
            </p>
          </div>
        </div>
      </header>

      {/* Event-Based Forecast Section */}
      <section>
        <NFLEventForecast
          forecast={eventForecast}
          isLoading={forecastLoading}
        />
      </section>

      {/* Main Grid */}
      <div className="grid gap-8 xl:grid-cols-3">
        {/* Left Column: Projections */}
        <div className="space-y-6 xl:col-span-2">
          <section className="space-y-4">
            <div className="flex items-start justify-between gap-4 rounded-lg border border-green-500/30 bg-green-500/10 p-3">
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-green-500/20">
                  <Activity className="h-5 w-5 text-green-400" />
                </div>
                <div>
                  <h2 className="text-lg font-semibold">Win Probabilities</h2>
                  <p className="text-xs text-gray-500">
                    External projection feeds
                  </p>
                </div>
              </div>
              <button
                onClick={() => refetchProjections()}
                className="flex items-center gap-1.5 rounded-lg bg-gray-800 px-3 py-1.5 text-xs transition-colors hover:bg-gray-700"
              >
                <RefreshCw className="h-3 w-3" />
                Refresh
              </button>
            </div>

            {/* Team Selector */}
            {Object.keys(projectionTeams).length > 0 && (
              <div className="rounded-lg border border-gray-800 bg-gray-900/40 p-3">
                <div className="mb-2">
                  <span className="text-xs text-gray-500">Select Team:</span>
                </div>
                <div className="flex flex-wrap gap-2">
                  {Object.values(projectionTeams).map((team) => {
                    const isActive = projectionSymbol === team;
                    const label = team.includes(":")
                      ? team.split(":")[1].replace("_", " ")
                      : team;
                    return (
                      <button
                        key={team}
                        onClick={() => setProjectionSymbol(team)}
                        className={`rounded-md px-3 py-1.5 text-xs font-medium transition-all ${
                          isActive
                            ? "bg-green-600 text-white"
                            : "bg-gray-800 text-gray-300 hover:bg-gray-700"
                        }`}
                      >
                        {label}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Projection Card */}
            {Object.keys(projectionTeams).length === 0 ? (
              <div className="rounded-xl border border-gray-700 bg-gray-800/50 p-6 text-center text-gray-400">
                <p>No projection targets configured.</p>
                <p className="mt-1 text-xs text-gray-500">
                  Add targets via BAKER_TEAM_MAP or extend the ingestion layer.
                </p>
              </div>
            ) : (
              <ProjectionCard
                symbol={projectionSymbol}
                projections={projections}
                isLoading={projectionsLoading}
              />
            )}
          </section>
        </div>

        {/* Right Column: Events */}
        <aside className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Newspaper className="h-4 w-4 text-blue-400" />
              <h2 className="font-semibold">Sports Events</h2>
            </div>
            <a
              href="/events"
              className="flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300"
            >
              All events <ArrowRight className="h-3 w-3" />
            </a>
          </div>

          <div className="rounded-lg border border-green-500/20 bg-green-500/5 p-3">
            <p className="text-xs text-gray-400">
              Showing sports and NFL news events
            </p>
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
          ) : events && events.length > 0 ? (
            <EventList events={events} />
          ) : (
            <div className="rounded-lg border border-gray-700 bg-gray-800/50 p-4 text-center text-sm text-gray-500">
              No sports events found.
              <p className="mt-1 text-xs">Run ingestion to populate.</p>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
