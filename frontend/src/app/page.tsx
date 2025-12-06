"use client";

import { useQuery } from "@tanstack/react-query";
import {
  TrendingUp,
  Zap,
  Target,
  Activity,
  ArrowRight,
} from "lucide-react";
import Link from "next/link";
import {
  getHealth,
  getRecentEvents,
} from "@/lib/api";

export default function Dashboard() {
  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
    refetchInterval: 30000,
    staleTime: 30000,
  });

  const { data: recentEvents } = useQuery({
    queryKey: ["recent-events"],
    queryFn: () => getRecentEvents(6),
    staleTime: 3 * 60 * 1000,
  });

  return (
    <div className="space-y-10">
      {/* Header */}
      <header className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-4xl font-bold">ForecastGPT</h1>
            <p className="mt-2 text-lg text-gray-400">
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

      {/* Navigation Cards */}
      <section>
        <h2 className="mb-4 text-xl font-semibold">Select a Forecast Domain</h2>
        <div className="grid gap-6 md:grid-cols-2">
          {/* Crypto Card */}
          <Link href="/crypto">
            <div className="group cursor-pointer rounded-xl border border-orange-500/30 bg-gradient-to-br from-orange-500/10 to-orange-500/5 p-6 transition-all hover:border-orange-500/50 hover:shadow-lg hover:shadow-orange-500/10">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-orange-500/20">
                    <TrendingUp className="h-6 w-6 text-orange-400" />
                  </div>
                  <div>
                    <h3 className="text-xl font-semibold">Crypto Forecasts</h3>
                    <p className="mt-1 text-sm text-gray-400">
                      ML-powered return predictions
                    </p>
                  </div>
                </div>
                <ArrowRight className="h-5 w-5 text-gray-500 transition-transform group-hover:translate-x-1" />
              </div>
              <div className="mt-4 space-y-2 text-sm text-gray-400">
                <p>• BTC, ETH, XMR price forecasts</p>
                <p>• Semantic event context</p>
                <p>• Multiple time horizons</p>
              </div>
            </div>
          </Link>

          {/* NFL Card */}
          <Link href="/nfl">
            <div className="group cursor-pointer rounded-xl border border-green-500/30 bg-gradient-to-br from-green-500/10 to-green-500/5 p-6 transition-all hover:border-green-500/50 hover:shadow-lg hover:shadow-green-500/10">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-green-500/20">
                    <Activity className="h-6 w-6 text-green-400" />
                  </div>
                  <div>
                    <h3 className="text-xl font-semibold">NFL Projections</h3>
                    <p className="mt-1 text-sm text-gray-400">
                      Win probability tracking
                    </p>
                  </div>
                </div>
                <ArrowRight className="h-5 w-5 text-gray-500 transition-transform group-hover:translate-x-1" />
              </div>
              <div className="mt-4 space-y-2 text-sm text-gray-400">
                <p>• Live game projections</p>
                <p>• Sports event context</p>
                <p>• Historical trend analysis</p>
              </div>
            </div>
          </Link>
        </div>
      </section>

      {/* Recent Activity */}
      {recentEvents && recentEvents.length > 0 && (
        <section className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-xl font-semibold">Recent Events</h2>
            <Link
              href="/events"
              className="flex items-center gap-1 text-sm text-blue-400 hover:text-blue-300"
            >
              View all <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            {recentEvents.slice(0, 6).map((event) => (
              <Link
                key={event.id}
                href={`/events/${event.id}`}
                className="group rounded-lg border border-gray-800 bg-gray-900/30 p-4 transition-colors hover:border-gray-700"
              >
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-xs text-gray-500">
                    {event.source || "Unknown"}
                  </span>
                  <span className="text-xs text-gray-500">
                    {new Date(event.timestamp).toLocaleDateString()}
                  </span>
                </div>
                <h4 className="mb-1 text-sm font-medium text-gray-200 group-hover:text-white">
                  {event.title}
                </h4>
                {event.summary && (
                  <p className="line-clamp-2 text-xs text-gray-400">
                    {event.summary}
                  </p>
                )}
              </Link>
            ))}
          </div>
        </section>
      )}

      {/* How it Works */}
      <footer className="space-y-3 rounded-xl border border-gray-800 bg-gray-900/30 p-6">
        <h3 className="text-lg font-semibold text-gray-300">How ForecastGPT Works</h3>
        <div className="grid gap-6 text-sm text-gray-400 md:grid-cols-3">
          <div>
            <p className="mb-2 font-semibold text-gray-300">1. Ingest</p>
            <p>
              Domain-specific events (crypto news, sports news) and numeric data
              are ingested from categorized RSS feeds and APIs.
            </p>
          </div>
          <div>
            <p className="mb-2 font-semibold text-gray-300">2. Embed & Match</p>
            <p>
              Text is embedded with OpenAI. When forecasting, we find
              semantically similar past events and their outcomes.
            </p>
          </div>
          <div>
            <p className="mb-2 font-semibold text-gray-300">3. Forecast</p>
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
