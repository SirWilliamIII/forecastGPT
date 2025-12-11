"use client";

import type { NFLTeamStats } from "@/types/api";

interface TeamStatsCardProps {
  stats: NFLTeamStats | undefined;
  isLoading?: boolean;
}

export function TeamStatsCard({ stats, isLoading }: TeamStatsCardProps) {
  if (isLoading) {
    return (
      <div className="rounded-xl border border-gray-800 bg-gray-900/50 p-6">
        <div className="animate-pulse space-y-4">
          <div className="h-8 bg-gray-800 rounded w-1/3" />
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-24 bg-gray-800 rounded" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (!stats) {
    return (
      <div className="rounded-xl border border-gray-800 bg-gray-900/50 p-6 text-center">
        <p className="text-gray-400">No statistics available</p>
      </div>
    );
  }

  const winPct = (stats.win_percentage * 100).toFixed(1);
  const seasonWinPct = (stats.current_season_win_pct * 100).toFixed(1);
  const streakIsWin = stats.current_streak.startsWith("W");

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900/50 p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold">{stats.display_name}</h2>
          <p className="text-sm text-gray-400">Team Statistics</p>
        </div>
        <div
          className={`rounded-lg px-4 py-2 text-center ${
            streakIsWin
              ? "bg-green-500/20 text-green-400"
              : "bg-red-500/20 text-red-400"
          }`}
        >
          <p className="text-xs text-gray-400">Current Streak</p>
          <p className="text-2xl font-bold">{stats.current_streak}</p>
        </div>
      </div>

      {/* Main Stats Grid */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        {/* Overall Record */}
        <div className="rounded-lg bg-gray-800/50 p-4">
          <p className="text-xs text-gray-400 mb-1">Overall Record</p>
          <p className="text-2xl font-bold">
            {stats.total_wins}-{stats.total_losses}
          </p>
          <p className="text-sm text-gray-400">{winPct}% Win Rate</p>
        </div>

        {/* 2024 Season */}
        <div className="rounded-lg bg-gray-800/50 p-4">
          <p className="text-xs text-gray-400 mb-1">2024 Season</p>
          <p className="text-2xl font-bold">
            {stats.current_season_wins}-{stats.current_season_losses}
          </p>
          <p className="text-sm text-gray-400">{seasonWinPct}% Win Rate</p>
        </div>

        {/* Total Games */}
        <div className="rounded-lg bg-gray-800/50 p-4">
          <p className="text-xs text-gray-400 mb-1">Total Games</p>
          <p className="text-2xl font-bold">{stats.total_games}</p>
          <p className="text-sm text-gray-400">Since 2012</p>
        </div>

        {/* Avg Point Differential */}
        <div className="rounded-lg bg-gray-800/50 p-4">
          <p className="text-xs text-gray-400 mb-1">Avg Point Diff</p>
          <p
            className={`text-2xl font-bold ${
              stats.avg_point_differential >= 0
                ? "text-green-400"
                : "text-red-400"
            }`}
          >
            {stats.avg_point_differential >= 0 ? "+" : ""}
            {stats.avg_point_differential.toFixed(1)}
          </p>
          <p className="text-sm text-gray-400">Per Game</p>
        </div>
      </div>

      {/* Recent Games */}
      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-gray-300">
          Last 10 Games
        </h3>
        <div className="grid gap-2">
          {stats.recent_games.map((game, idx) => {
            const isWin = game.result === "WIN";
            const date = new Date(game.date);
            return (
              <div
                key={idx}
                className={`flex items-center justify-between rounded-lg border p-3 ${
                  isWin
                    ? "border-green-500/30 bg-green-500/5"
                    : "border-red-500/30 bg-red-500/5"
                }`}
              >
                <div className="flex items-center gap-3">
                  <div
                    className={`rounded px-2 py-1 text-xs font-bold ${
                      isWin
                        ? "bg-green-600 text-white"
                        : "bg-red-600 text-white"
                    }`}
                  >
                    {game.result}
                  </div>
                  <span className="text-sm text-gray-300">
                    {date.toLocaleDateString(undefined, {
                      month: "short",
                      day: "numeric",
                      year: "numeric",
                    })}
                  </span>
                </div>
                <div className="text-right">
                  <p
                    className={`text-sm font-mono ${
                      game.point_differential >= 0
                        ? "text-green-400"
                        : "text-red-400"
                    }`}
                  >
                    {game.point_differential >= 0 ? "+" : ""}
                    {game.point_differential.toFixed(0)}
                  </p>
                  <p className="text-xs text-gray-500">Point Diff</p>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
