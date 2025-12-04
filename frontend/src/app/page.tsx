"use client";

import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  RefreshCw,
  TrendingUp,
  Zap,
  Newspaper,
  ArrowRight,
  Info,
  Target,
  Activity,
} from "lucide-react";
import { ForecastCard } from "@/components/ForecastCard";
import { SymbolSelector } from "@/components/SymbolSelector";
import { HorizonSelector } from "@/components/HorizonSelector";
import { EventList } from "@/components/EventList";
import { ProjectionCard } from "@/components/ProjectionCard";
import {
  getAssetForecast,
  getRecentEvents,
  getHealth,
  getLatestProjections,
  getProjectionTeams,
  getAvailableSymbols,
  getAvailableHorizons,
  type EventDomain,
  type AvailableHorizon,
} from "@/lib/api";

type ActiveSection = "crypto" | "sports";

export default function Dashboard() {
  const [symbol, setSymbol] = useState<string>("BTC-USD");
  const [availableSymbols, setAvailableSymbols] = useState<string[]>([]);
  const [horizon, setHorizon] = useState(1440);
  const [availableHorizons, setAvailableHorizons] = useState<AvailableHorizon[]>([]);
  const [projectionSymbol, setProjectionSymbol] =
    useState<string>("NFL:KC_CHIEFS");
  const [projectionTeams, setProjectionTeams] = useState<
    Record<string, string>
  >({});
  const [activeSection, setActiveSection] = useState<ActiveSection>("crypto");

  // Determine event domain based on active section
  const eventDomain: EventDomain = activeSection === "sports" ? "sports" : "crypto";

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
    queryKey: ["events", eventDomain],
    queryFn: () => getRecentEvents(10, undefined, eventDomain),
    staleTime: 3 * 60 * 1000,
    gcTime: 20 * 60 * 1000,
  });

  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
    refetchInterval: 30000,
    staleTime: 30000,
  });

  const {
    data: projections,
    isLoading: projectionsLoading,
    refetch: refetchProjections,
  } = useQuery({
    queryKey: ["projections", projectionSymbol],
    queryFn: () => getLatestProjections(projectionSymbol, "win_prob", 5),
    staleTime: 5 * 60 * 1000,
    gcTime: 30 * 60 * 1000,
  });

  const { data: teamsData } = useQuery({
    queryKey: ["projection-teams"],
    queryFn: getProjectionTeams,
    staleTime: 60 * 60 * 1000,
    gcTime: 24 * 60 * 60 * 1000,
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

  // Update available symbols when data changes
  useEffect(() => {
    if (symbolsData && symbolsData.crypto.length > 0) {
      setAvailableSymbols(symbolsData.crypto);
      // Set initial symbol if current one isn't in the list
      if (symbol && !symbolsData.crypto.includes(symbol)) {
        setSymbol(symbolsData.crypto[0]);
      }
    }
  }, [symbolsData, symbol]);

  // Update available horizons when data changes
  useEffect(() => {
    if (horizonsData && horizonsData.length > 0) {
      setAvailableHorizons(horizonsData);
      // Set initial horizon if current one isn't in the list
      const availableValues = horizonsData.map(h => h.value);
      if (horizon && !availableValues.includes(horizon)) {
        setHorizon(horizonsData[0].value);
      }
    }
  }, [horizonsData, horizon]);

  // Update projection teams when data changes
  useEffect(() => {
    if (teamsData && Object.keys(teamsData).length > 0) {
      setProjectionTeams(teamsData);
      const teamValues = Object.values(teamsData);
      if (teamValues.length > 0 && !teamValues.includes(projectionSymbol)) {
        setProjectionSymbol(teamValues[0]);
      }
    }
  }, [teamsData, projectionSymbol]);

  const domainLabels: Record<EventDomain, string> = {
    crypto: "Crypto & Blockchain",
    sports: "Sports & NFL",
    tech: "Tech & AI",
    general: "General",
  };

  return (
    <div className="space-y-10">
      {/* ═══════════════════════════════════════════════════════════════════ */}
      {/* HEADER                                                              */}
      {/* ═══════════════════════════════════════════════════════════════════ */}
      <header className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">ForecastGPT</h1>
            <p className="mt-1 text-gray-400">
              Semantic forecasting for any target, any metric, any horizon
            </p>
          </div>
          <div className="flex items-center gap-4">
            {health && (
              <div className="flex items-center gap-2 rounded-lg bg-gray-900/50 px-3 py-1.5">
                <span
                  className={`h-2 w-2 rounded-full ${
                    health.status === "healthy" ? "bg-green-500" : "bg-red-500"
                  }`}
                />
                <span className="text-sm text-gray-400">
                  {health.status === "healthy" ? "System OK" : "Degraded"}
                </span>
              </div>
            )}
          </div>
        </div>

        {/* System Overview */}
        <div className="grid gap-4 sm:grid-cols-3">
          <div className="flex items-center gap-3 rounded-lg border border-gray-800 bg-gray-900/30 p-3">
            <Target className="h-5 w-5 text-blue-400" />
            <div>
              <p className="text-xs text-gray-500">Targets</p>
              <p className="text-sm font-medium">
                Crypto, NFL, Equities, Custom
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3 rounded-lg border border-gray-800 bg-gray-900/30 p-3">
            <Activity className="h-5 w-5 text-green-400" />
            <div>
              <p className="text-xs text-gray-500">Metrics</p>
              <p className="text-sm font-medium">
                Returns, Win Prob, Ratings, ...
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3 rounded-lg border border-gray-800 bg-gray-900/30 p-3">
            <Zap className="h-5 w-5 text-yellow-400" />
            <div>
              <p className="text-xs text-gray-500">Horizons</p>
              <p className="text-sm font-medium">1h → 24h → 1w → 1mo+</p>
            </div>
          </div>
        </div>
      </header>

      {/* ═══════════════════════════════════════════════════════════════════ */}
      {/* MAIN GRID: Forecasts + Events                                       */}
      {/* ═══════════════════════════════════════════════════════════════════ */}
      <div className="grid gap-8 xl:grid-cols-3">
        {/* LEFT COLUMN: Forecasts (2/3 width on xl) */}
        <div className="space-y-8 xl:col-span-2">
          {/* ─────────────────────────────────────────────────────────────── */}
          {/* SECTION: ML Forecasts (Crypto)                                  */}
          {/* ─────────────────────────────────────────────────────────────── */}
          <section 
            className="space-y-4"
            onClick={() => setActiveSection("crypto")}
          >
            <div className={`flex items-start justify-between gap-4 rounded-lg p-3 transition-colors ${
              activeSection === "crypto" 
                ? "border border-orange-500/30 bg-orange-500/10" 
                : "border border-gray-800 bg-gray-900/30 hover:border-gray-700"
            }`}>
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-orange-500/20">
                  <TrendingUp className="h-5 w-5 text-orange-400" />
                </div>
                <div>
                  <h2 className="text-lg font-semibold">Crypto Forecasts</h2>
                  <p className="text-xs text-gray-500">
                    ML models predicting returns
                  </p>
                </div>
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  refetchForecast();
                }}
                className="flex items-center gap-1.5 rounded-lg bg-gray-800 px-3 py-1.5 text-xs transition-colors hover:bg-gray-700"
              >
                <RefreshCw className="h-3 w-3" />
                Refresh
              </button>
            </div>

            {/* Target + Horizon Selectors */}
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

            {/* Forecast Output */}
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

          {/* ─────────────────────────────────────────────────────────────── */}
          {/* SECTION: External Projections (NFL)                             */}
          {/* ─────────────────────────────────────────────────────────────── */}
          <section 
            className="space-y-4"
            onClick={() => setActiveSection("sports")}
          >
            <div className={`flex items-start justify-between gap-4 rounded-lg p-3 transition-colors ${
              activeSection === "sports" 
                ? "border border-green-500/30 bg-green-500/10" 
                : "border border-gray-800 bg-gray-900/30 hover:border-gray-700"
            }`}>
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-green-500/20">
                  <Activity className="h-5 w-5 text-green-400" />
                </div>
                <div>
                  <h2 className="text-lg font-semibold">NFL Projections</h2>
                  <p className="text-xs text-gray-500">
                    Win probabilities from external feeds
                  </p>
                </div>
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  refetchProjections();
                }}
                className="flex items-center gap-1.5 rounded-lg bg-gray-800 px-3 py-1.5 text-xs transition-colors hover:bg-gray-700"
              >
                <RefreshCw className="h-3 w-3" />
                Refresh
              </button>
            </div>

            {/* Target Selector */}
            {Object.keys(projectionTeams).length > 0 && (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs text-gray-500">Team:</span>
                {Object.values(projectionTeams).map((team) => {
                  const isActive = projectionSymbol === team;
                  const label = team.includes(":")
                    ? team.split(":")[1].replace("_", " ")
                    : team;
                  return (
                    <button
                      key={team}
                      onClick={(e) => {
                        e.stopPropagation();
                        setProjectionSymbol(team);
                      }}
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
            )}

            {/* Projection Output */}
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

        {/* RIGHT COLUMN: Events (1/3 width on xl) */}
        <aside className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Newspaper className="h-4 w-4 text-blue-400" />
              <h2 className="font-semibold">Related Events</h2>
            </div>
            <a
              href="/events"
              className="flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300"
            >
              All events <ArrowRight className="h-3 w-3" />
            </a>
          </div>

          {/* Domain indicator */}
          <div className={`rounded-lg p-3 ${
            activeSection === "crypto" 
              ? "border border-orange-500/20 bg-orange-500/5" 
              : "border border-green-500/20 bg-green-500/5"
          }`}>
            <p className="flex items-start gap-2 text-xs text-gray-400">
              <Info className="mt-0.5 h-3 w-3 shrink-0" />
              Showing <span className="font-medium text-white">{domainLabels[eventDomain]}</span> events.
              Click a forecast section to switch domains.
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
              No {domainLabels[eventDomain].toLowerCase()} events found.
              <p className="mt-1 text-xs">Run ingestion to populate.</p>
            </div>
          )}
        </aside>
      </div>

      {/* ═══════════════════════════════════════════════════════════════════ */}
      {/* FOOTER: How it works                                                */}
      {/* ═══════════════════════════════════════════════════════════════════ */}
      <footer className="space-y-3 rounded-xl border border-gray-800 bg-gray-900/30 p-4">
        <h3 className="text-sm font-medium text-gray-300">How ForecastGPT Works</h3>
        <div className="grid gap-4 text-xs text-gray-500 sm:grid-cols-3">
          <div>
            <p className="mb-1 font-medium text-gray-400">1. Ingest</p>
            <p>
              Domain-specific events (crypto news, sports news) and numeric data 
              are ingested from categorized RSS feeds and APIs.
            </p>
          </div>
          <div>
            <p className="mb-1 font-medium text-gray-400">2. Embed & Match</p>
            <p>
              Text is embedded with OpenAI. When forecasting, we find
              semantically similar past events and their outcomes.
            </p>
          </div>
          <div>
            <p className="mb-1 font-medium text-gray-400">3. Forecast</p>
            <p>
              ML models predict metric changes for any target/horizon, 
              conditioned on domain-relevant event context.
            </p>
          </div>
        </div>
      </footer>
    </div>
  );
}
