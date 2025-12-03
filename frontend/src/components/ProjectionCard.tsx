"use client";

import type { Projection, ProjectionSymbol } from "@/types/api";

const TEAM_INFO: Record<ProjectionSymbol, { name: string; color: string }> = {
  "NFL:KC_CHIEFS": { name: "Kansas City Chiefs", color: "bg-red-500" },
  "NFL:DAL_COWBOYS": { name: "Dallas Cowboys", color: "bg-blue-500" },
};

interface ProjectionCardProps {
  symbol: ProjectionSymbol;
  projections: Projection[] | undefined;
  isLoading?: boolean;
}

export function ProjectionCard({
  symbol,
  projections,
  isLoading,
}: ProjectionCardProps) {
  const info = TEAM_INFO[symbol];
  const latest = projections?.[0];
  const previous = projections && projections.length > 1 ? projections[1] : undefined;

  const delta =
    latest && previous
      ? (latest.projected_value - previous.projected_value) * 100
      : null;

  const opponent = latest?.opponent_name || latest?.opponent || "Opponent TBD";
  const isHome = latest?.meta && typeof latest.meta.home_team === "number" ? latest.meta.home_team >= 0.5 : null;
  const spread =
    latest?.meta && typeof latest.meta.spread === "number"
      ? latest.meta.spread
      : null;
  const total =
    latest?.meta && typeof latest.meta.over_under === "number"
      ? latest.meta.over_under
      : null;
  const trend = projections?.slice(0, 8).map((p) => p.projected_value) || [];
  const lastUpdated = latest ? new Date(latest.as_of) : null;

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900/50 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full ${info.color}`} />
          <div>
            <p className="text-sm text-gray-400">Projected Win Probability</p>
            <p className="text-lg font-semibold">{info.name}</p>
          </div>
        </div>
        {latest && (
          <span className="text-xs text-gray-500">
            Game ID {latest.game_id ?? "—"}
          </span>
        )}
      </div>

      {isLoading ? (
        <div className="animate-pulse rounded-lg bg-gray-800 h-16" />
      ) : latest ? (
        <>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                {isHome !== null && (
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
                      isHome ? "bg-green-700 text-green-50" : "bg-purple-700 text-purple-50"
                    }`}
                  >
                    {isHome ? "Home" : "Away"}
                  </span>
                )}
                <p className="text-sm text-gray-400">vs {opponent}</p>
              </div>
              <p className="text-4xl font-bold">
                {(latest.projected_value * 100).toFixed(1)}%
              </p>
              <p className="text-sm text-gray-400">
                as of {new Date(latest.as_of).toUTCString()}
              </p>
            </div>
            <div className="flex flex-col gap-2 text-sm">
              {spread !== null && (
                <div className="flex items-center gap-2 rounded bg-gray-900/80 px-2 py-1">
                  <span className="text-xs text-gray-500">Spread</span>
                  <span className="font-mono">{spread > 0 ? `+${spread.toFixed(1)}` : spread.toFixed(1)}</span>
                </div>
              )}
              {total !== null && (
                <div className="flex items-center gap-2 rounded bg-gray-900/80 px-2 py-1">
                  <span className="text-xs text-gray-500">Total (O/U)</span>
                  <span className="font-mono">{total.toFixed(1)}</span>
                </div>
              )}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
            <div className="rounded bg-gray-900/80 p-2">
              <p className="text-xs text-gray-500">Change vs prior</p>
              <p className={`font-mono ${delta !== null && delta >= 0 ? "text-green-400" : "text-red-400"}`}>
                {delta === null ? "—" : `${delta >= 0 ? "+" : ""}${delta.toFixed(1)}%`}
              </p>
            </div>
            <div className="rounded bg-gray-900/80 p-2">
              <p className="text-xs text-gray-500">Game time (UTC)</p>
              <p className="font-mono">
                {new Date(latest.as_of).toLocaleString(undefined, {
                  month: "short",
                  day: "numeric",
                  hour: "2-digit",
                  minute: "2-digit",
                  timeZone: "UTC",
                })}
              </p>
            </div>
            <div className="rounded bg-gray-900/80 p-2">
              <p className="text-xs text-gray-500">Runs ingested</p>
              <p className="font-mono">{projections?.length ?? 0}</p>
            </div>
            <div className="rounded bg-gray-900/80 p-2">
              <p className="text-xs text-gray-500">Model</p>
              <p className="font-mono uppercase">{latest.model_source || "baker"}</p>
            </div>
          </div>
          {trend.length > 1 && (
            <div className="space-y-1">
              <p className="text-xs text-gray-500">Trend (last {trend.length} runs)</p>
              <div className="flex items-end gap-1 h-16">
                {trend.map((v, idx) => {
                  const pct = Math.max(0, Math.min(1, v));
                  const height = 10 + pct * 50; // scale to 10-60px
                  return (
                    <div
                      key={idx}
                      className="w-6 rounded-t bg-blue-500/70"
                      style={{ height: `${height}px` }}
                      title={`${(v * 100).toFixed(1)}%`}
                    />
                  );
                })}
              </div>
            </div>
          )}
          {lastUpdated && (
            <p className="text-xs text-gray-500">
              Updated {lastUpdated.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })} UTC
            </p>
          )}
        </>
      ) : (
        <p className="text-sm text-gray-500">
          No projections available for this team yet.
        </p>
      )}

      {projections && projections.length > 1 && (
        <div className="space-y-2">
          <p className="text-xs text-gray-500">Recent runs</p>
          <div className="space-y-1">
            {projections.slice(0, 4).map((p) => (
              <div
                key={`${p.symbol}-${p.game_id}-${p.as_of}`}
                className="flex items-center justify-between rounded bg-gray-800/70 px-2 py-1 text-sm"
              >
                <span className="flex gap-2 items-center">
                  {new Date(p.as_of).toLocaleDateString(undefined, {
                    month: "short",
                    day: "numeric",
                  })}
                  {p.opponent && (
                    <span className="text-xs text-gray-500">vs {p.opponent.replace("_", " ")}</span>
                  )}
                </span>
                <span className="font-mono">
                  {(p.projected_value * 100).toFixed(1)}%
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
