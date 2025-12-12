"use client";

import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  RefreshCw,
  Activity,
  Newspaper,
  ArrowRight,
  Users,
  BarChart3,
} from "lucide-react";
import { EventList } from "@/components/EventList";
import { ProjectionCard } from "@/components/ProjectionCard";
import { NFLEventForecast } from "@/components/NFLEventForecast";
import { TeamSelector } from "@/components/TeamSelector";
import { TeamStatsCard } from "@/components/TeamStatsCard";
import { GamesTable } from "@/components/GamesTable";
import { ForecastTimeline, EventImpactCard } from "@/components/nfl";
import {
  getRecentEvents,
  getLatestProjections,
  getProjectionTeams,
  getNFLTeamForecast,
  getNFLTeams,
  getNFLTeamStats,
  getNFLTeamGames,
  getForecastTimeline,
  getEventImpacts,
} from "@/lib/api";

export default function NFLPage() {
  const [selectedTeam, setSelectedTeam] = useState<string>("NFL:DAL_COWBOYS");
  const [projectionTeams, setProjectionTeams] = useState<Record<string, string>>({});
  const [gamesPage, setGamesPage] = useState(1);
  const [gamesSeason, setGamesSeason] = useState<number | undefined>(undefined);
  const [gamesOutcome, setGamesOutcome] = useState<"win" | "loss" | "all" | undefined>(undefined);

  // Fetch available teams
  const { data: teams, isLoading: teamsLoading } = useQuery({
    queryKey: ["nfl-teams"],
    queryFn: getNFLTeams,
    staleTime: 60 * 60 * 1000, // 1 hour
    gcTime: 24 * 60 * 60 * 1000, // 24 hours
  });

  // Set default team when teams load
  useEffect(() => {
    if (teams && teams.length > 0 && !teams.find(t => t.symbol === selectedTeam)) {
      setSelectedTeam(teams[0].symbol);
    }
  }, [teams, selectedTeam]);

  // Fetch team stats
  const {
    data: teamStats,
    isLoading: statsLoading,
    refetch: refetchStats,
  } = useQuery({
    queryKey: ["nfl-team-stats", selectedTeam],
    queryFn: () => getNFLTeamStats(selectedTeam),
    enabled: !!selectedTeam,
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 30 * 60 * 1000, // 30 minutes
  });

  // Fetch team games with pagination and filters
  const {
    data: teamGames,
    isLoading: gamesLoading,
    refetch: refetchGames,
  } = useQuery({
    queryKey: ["nfl-team-games", selectedTeam, gamesPage, gamesSeason, gamesOutcome],
    queryFn: () => getNFLTeamGames(selectedTeam, gamesPage, 20, gamesSeason, gamesOutcome),
    enabled: !!selectedTeam,
    staleTime: 5 * 60 * 1000,
    gcTime: 30 * 60 * 1000,
  });

  // Fetch events for selected team
  const {
    data: events,
    isLoading: eventsLoading,
    refetch: refetchEvents,
  } = useQuery({
    queryKey: ["events", "sports", selectedTeam],
    queryFn: () => getRecentEvents(50, undefined, "sports", selectedTeam),
    enabled: !!selectedTeam,
    staleTime: 3 * 60 * 1000,
    gcTime: 20 * 60 * 1000,
  });

  // Fetch projections
  const {
    data: projections,
    isLoading: projectionsLoading,
    refetch: refetchProjections,
  } = useQuery({
    queryKey: ["projections", selectedTeam],
    queryFn: () => getLatestProjections(selectedTeam, "win_prob", 10),
    enabled: !!selectedTeam,
    staleTime: 5 * 60 * 1000,
    gcTime: 30 * 60 * 1000,
  });

  // Fetch projection teams config
  const { data: teamsData } = useQuery({
    queryKey: ["projection-teams"],
    queryFn: getProjectionTeams,
    staleTime: 60 * 60 * 1000,
    gcTime: 24 * 60 * 60 * 1000,
  });

  // Fetch event-based forecast
  const {
    data: eventForecast,
    isLoading: forecastLoading,
    refetch: refetchForecast,
  } = useQuery({
    queryKey: ["nfl-event-forecast", selectedTeam],
    queryFn: () => getNFLTeamForecast(selectedTeam, true),
    enabled: !!selectedTeam,
    staleTime: 5 * 60 * 1000,
    gcTime: 30 * 60 * 1000,
  });

  // Fetch forecast timeline
  const {
    data: forecastTimeline,
    isLoading: timelineLoading,
    refetch: refetchTimeline,
  } = useQuery({
    queryKey: ["nfl-forecast-timeline", selectedTeam],
    queryFn: () => getForecastTimeline(selectedTeam, 30),
    enabled: !!selectedTeam,
    staleTime: 5 * 60 * 1000,
    gcTime: 30 * 60 * 1000,
  });

  // Fetch event impacts
  const {
    data: eventImpacts,
    isLoading: impactsLoading,
    refetch: refetchImpacts,
  } = useQuery({
    queryKey: ["nfl-event-impacts", selectedTeam],
    queryFn: () => getEventImpacts(selectedTeam, 10),
    enabled: !!selectedTeam,
    staleTime: 5 * 60 * 1000,
    gcTime: 30 * 60 * 1000,
  });

  useEffect(() => {
    if (teamsData && Object.keys(teamsData).length > 0) {
      setProjectionTeams(teamsData);
    }
  }, [teamsData]);

  // Reset page when filters change
  useEffect(() => {
    setGamesPage(1);
  }, [gamesSeason, gamesOutcome]);

  const handlePageChange = (page: number) => {
    setGamesPage(page);
  };

  const handleSeasonChange = (season: number | undefined) => {
    setGamesSeason(season);
  };

  const handleOutcomeChange = (outcome: "win" | "loss" | "all" | undefined) => {
    setGamesOutcome(outcome);
  };

  const handleRefreshAll = () => {
    refetchStats();
    refetchGames();
    refetchEvents();
    refetchProjections();
    refetchForecast();
    refetchTimeline();
    refetchImpacts();
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <header className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">NFL Analytics</h1>
            <p className="mt-1 text-gray-400">
              Team statistics, game history, and predictions
            </p>
          </div>
          <button
            onClick={handleRefreshAll}
            className="flex items-center gap-2 rounded-lg bg-gray-800 px-4 py-2 text-sm transition-colors hover:bg-gray-700"
          >
            <RefreshCw className="h-4 w-4" />
            Refresh All
          </button>
        </div>
      </header>

      {/* Team Selector */}
      <TeamSelector
        teams={teams}
        selectedTeam={selectedTeam}
        onTeamChange={setSelectedTeam}
        isLoading={teamsLoading}
      />

      {/* Event-Based Forecast Section */}
      <section>
        <NFLEventForecast
          forecast={eventForecast}
          isLoading={forecastLoading}
        />
      </section>

      {/* Forecast Timeline */}
      <section>
        <ForecastTimeline
          data={forecastTimeline}
          isLoading={timelineLoading}
        />
      </section>

      {/* Main Content Grid */}
      <div className="grid gap-6 lg:grid-cols-3">
        {/* Left Column: Stats and Games */}
        <div className="space-y-6 lg:col-span-2">
          {/* Team Stats Card */}
          <section className="space-y-4">
            <div className="flex items-center gap-3 rounded-lg border border-blue-500/30 bg-blue-500/10 p-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-500/20">
                <BarChart3 className="h-5 w-5 text-blue-400" />
              </div>
              <div>
                <h2 className="text-lg font-semibold">Team Statistics</h2>
                <p className="text-xs text-gray-500">
                  Historical performance and metrics
                </p>
              </div>
            </div>

            <TeamStatsCard stats={teamStats} isLoading={statsLoading} />
          </section>

          {/* Games Table */}
          <section className="space-y-4">
            <div className="flex items-center gap-3 rounded-lg border border-purple-500/30 bg-purple-500/10 p-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-purple-500/20">
                <Users className="h-5 w-5 text-purple-400" />
              </div>
              <div>
                <h2 className="text-lg font-semibold">Game History</h2>
                <p className="text-xs text-gray-500">
                  Complete game-by-game results
                </p>
              </div>
            </div>

            <GamesTable
              data={teamGames}
              isLoading={gamesLoading}
              onPageChange={handlePageChange}
              onSeasonChange={handleSeasonChange}
              onOutcomeChange={handleOutcomeChange}
            />
          </section>
        </div>

        {/* Right Column: Projections and Events */}
        <aside className="space-y-6">
          {/* Event Impacts */}
          <section>
            <EventImpactCard
              impacts={eventImpacts}
              isLoading={impactsLoading}
            />
          </section>

          {/* Projections */}
          <section className="space-y-4">
            <div className="flex items-center gap-3 rounded-lg border border-green-500/30 bg-green-500/10 p-3">
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

            {Object.keys(projectionTeams).length === 0 ? (
              <div className="rounded-xl border border-gray-700 bg-gray-800/50 p-6 text-center text-gray-400">
                <p>No projection targets configured.</p>
                <p className="mt-1 text-xs text-gray-500">
                  Add targets via BAKER_TEAM_MAP or extend the ingestion layer.
                </p>
              </div>
            ) : (
              <ProjectionCard
                symbol={selectedTeam}
                projections={projections}
                isLoading={projectionsLoading}
              />
            )}
          </section>

          {/* Events */}
          <section className="space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Newspaper className="h-4 w-4 text-blue-400" />
                <h2 className="font-semibold">Team Events</h2>
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
                Showing events relevant to selected team
              </p>
            </div>

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
                No sports events found for this team.
                <p className="mt-1 text-xs">Run ingestion to populate.</p>
              </div>
            )}
          </section>
        </aside>
      </div>
    </div>
  );
}
