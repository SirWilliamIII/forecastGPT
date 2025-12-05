"use client";

import type { Projection } from "@/types/api";

interface ProjectionCardProps {
  symbol: string;
  projections: Projection[] | undefined;
  isLoading?: boolean;
}

function getSymbolInfo(symbol: string): { name: string; color: string } {
  // NFL teams
  if (symbol.startsWith("NFL:")) {
    const team = symbol.replace("NFL:", "").replace("_", " ");
    const colors: Record<string, string> = {
      "KC CHIEFS": "bg-red-500",
      "DAL COWBOYS": "bg-blue-500",
      "SF 49ERS": "bg-red-600",
      "PHI EAGLES": "bg-green-600",
    };
    return { name: team, color: colors[team] || "bg-gray-500" };
  }
  // Crypto
  if (symbol.includes("-USD")) {
    const asset = symbol.replace("-USD", "");
    const colors: Record<string, string> = {
      BTC: "bg-orange-500",
      ETH: "bg-purple-500",
      XMR: "bg-gray-500",
    };
    return { name: asset, color: colors[asset] || "bg-blue-500" };
  }
  // Equities
  if (symbol.match(/^[A-Z]{1,5}$/)) {
    return { name: symbol, color: "bg-emerald-500" };
  }
  // Default
  return { name: symbol, color: "bg-gray-500" };
}

export function ProjectionCard({
  symbol,
  projections,
  isLoading,
}: ProjectionCardProps) {
  const info = getSymbolInfo(symbol);
  const latest = projections?.[0];
  const previous =
    projections && projections.length > 1 ? projections[1] : undefined;

  const delta =
    latest && previous
      ? (latest.projected_value - previous.projected_value) * 100
      : null;

  const opponent = latest?.opponent_name || latest?.opponent || null;
  const isHome =
    latest?.meta && typeof latest.meta.home_team === "number"
      ? latest.meta.home_team >= 0.5
      : null;
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

  // Determine if this is a probability (0-1) or other metric
  const isProbability =
    latest && latest.projected_value >= 0 && latest.projected_value <= 1;
  const formatValue = (v: number) =>
    isProbability ? `${(v * 100).toFixed(1)}%` : v.toFixed(2);

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900/50 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full ${info.color}`} />
          <div>
            <p className="text-sm text-gray-400">
              {latest?.metric?.replace("_", " ") || "Projection"}
            </p>
            <p className="text-lg font-semibold">{info.name}</p>
          </div>
        </div>
        {latest?.game_id && (
          <span className="text-xs text-gray-500">ID {latest.game_id}</span>
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
                      isHome
                        ? "bg-green-700 text-green-50"
                        : "bg-purple-700 text-purple-50"
                    }`}
                  >
                    {isHome ? "Home" : "Away"}
                  </span>
                )}
                {opponent && (
                  <p className="text-sm text-gray-400">vs {opponent}</p>
                )}
              </div>
              <p className="text-4xl font-bold">
                {formatValue(latest.projected_value)}
              </p>
              <p className="text-sm text-gray-400">
                as of {new Date(latest.as_of).toUTCString()}
              </p>
            </div>
            <div className="flex flex-col gap-2 text-sm">
              {spread !== null && (
                <div className="flex items-center gap-2 rounded bg-gray-900/80 px-2 py-1">
                  <span className="text-xs text-gray-500">Spread</span>
                  <span className="font-mono">
                    {spread > 0 ? `+${spread.toFixed(1)}` : spread.toFixed(1)}
                  </span>
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
              <p
                className={`font-mono ${delta !== null && delta >= 0 ? "text-green-400" : "text-red-400"}`}
              >
                {delta === null
                  ? "—"
                  : `${delta >= 0 ? "+" : ""}${delta.toFixed(1)}%`}
              </p>
            </div>
            <div className="rounded bg-gray-900/80 p-2">
              <p className="text-xs text-gray-500">Horizon</p>
              <p className="font-mono">
                {latest.horizon_minutes >= 1440
                  ? `${Math.round(latest.horizon_minutes / 1440)}d`
                  : `${Math.round(latest.horizon_minutes / 60)}h`}
              </p>
            </div>
            <div className="rounded bg-gray-900/80 p-2">
              <p className="text-xs text-gray-500">Data points</p>
              <p className="font-mono">{projections?.length ?? 0}</p>
            </div>
            <div className="rounded bg-gray-900/80 p-2">
              <p className="text-xs text-gray-500">Source</p>
              <p className="font-mono uppercase">
                {latest.model_source || "unknown"}
              </p>
            </div>
          </div>
          {trend.length > 1 && (
            <div className="space-y-1">
              <p className="text-xs text-gray-500">
                Trend (last {trend.length} updates)
              </p>
              <div className="flex items-end gap-1 h-16">
                {trend.map((v, idx) => {
                  const pct = isProbability
                    ? Math.max(0, Math.min(1, v))
                    : v / Math.max(...trend);
                  const height = 10 + pct * 50;
                  return (
                    <div
                      key={idx}
                      className="w-6 rounded-t bg-blue-500/70"
                      style={{ height: `${height}px` }}
                      title={formatValue(v)}
                    />
                  );
                })}
              </div>
            </div>
          )}
          {lastUpdated && (
            <p className="text-xs text-gray-500">
              Updated{" "}
              {lastUpdated.toLocaleString(undefined, {
                month: "short",
                day: "numeric",
                hour: "2-digit",
                minute: "2-digit",
              })}{" "}
              UTC
            </p>
          )}
        </>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-gray-500">
            No projections available for this target yet.
          </p>
          <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/10 p-3">
            <p className="text-xs font-semibold text-yellow-400">Setup Required</p>
            <p className="mt-1 text-xs text-gray-400">
              To enable NFL projections, set the <code className="rounded bg-gray-900 px-1 py-0.5">BAKER_API_KEY</code> environment variable in <code className="rounded bg-gray-900 px-1 py-0.5">backend/.env</code> and run the Baker projections ingestion:
            </p>
            <pre className="mt-2 rounded bg-gray-900 p-2 text-xs text-gray-300">
cd backend && uv run python -m ingest.baker_projections
            </pre>
          </div>
        </div>
      )}

      {projections && projections.length > 1 && (
        <div className="space-y-2">
          <p className="text-xs text-gray-500">Recent updates</p>
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
                    <span className="text-xs text-gray-500">
                      vs {p.opponent.replace("_", " ")}
                    </span>
                  )}
                </span>
                <span className="font-mono">{formatValue(p.projected_value)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
