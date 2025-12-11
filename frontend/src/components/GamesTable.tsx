"use client";

import { useState } from "react";
import type { NFLGamesResponse } from "@/types/api";
import { ChevronLeft, ChevronRight, Filter } from "lucide-react";

interface GamesTableProps {
  data: NFLGamesResponse | undefined;
  isLoading?: boolean;
  onPageChange?: (page: number) => void;
  onSeasonChange?: (season: number | undefined) => void;
  onOutcomeChange?: (outcome: "win" | "loss" | "all" | undefined) => void;
}

export function GamesTable({
  data,
  isLoading,
  onPageChange,
  onSeasonChange,
  onOutcomeChange,
}: GamesTableProps) {
  const [selectedSeason, setSelectedSeason] = useState<number | undefined>(
    undefined
  );
  const [selectedOutcome, setSelectedOutcome] = useState<
    "win" | "loss" | "all" | undefined
  >(undefined);

  // Generate season options (2012-2024)
  const seasons = Array.from({ length: 13 }, (_, i) => 2024 - i);

  const handleSeasonChange = (season: number | undefined) => {
    setSelectedSeason(season);
    onSeasonChange?.(season);
  };

  const handleOutcomeChange = (outcome: "win" | "loss" | "all" | undefined) => {
    setSelectedOutcome(outcome);
    onOutcomeChange?.(outcome);
  };

  if (isLoading) {
    return (
      <div className="rounded-xl border border-gray-800 bg-gray-900/50 p-6">
        <div className="animate-pulse space-y-3">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-16 bg-gray-800 rounded" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900/50 p-6 space-y-4">
      {/* Header with Filters */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h3 className="text-lg font-semibold">Game History</h3>
          <p className="text-sm text-gray-400">
            {data?.total_games ?? 0} total games
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Filter className="h-4 w-4 text-gray-400" />
          <select
            value={selectedSeason ?? ""}
            onChange={(e) =>
              handleSeasonChange(e.target.value ? Number(e.target.value) : undefined)
            }
            className="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-sm text-gray-300 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">All Seasons</option>
            {seasons.map((year) => (
              <option key={year} value={year}>
                {year}
              </option>
            ))}
          </select>

          <select
            value={selectedOutcome ?? ""}
            onChange={(e) =>
              handleOutcomeChange(
                e.target.value as "win" | "loss" | "all" | undefined || undefined
              )
            }
            className="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-sm text-gray-300 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">All Results</option>
            <option value="win">Wins Only</option>
            <option value="loss">Losses Only</option>
          </select>
        </div>
      </div>

      {/* Games Table */}
      {data && data.games.length > 0 ? (
        <>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-800 text-left text-xs text-gray-400">
                  <th className="pb-3">Date</th>
                  <th className="pb-3">Result</th>
                  <th className="pb-3 text-right">Team Score</th>
                  <th className="pb-3 text-right">Opp Score</th>
                  <th className="pb-3 text-right">Point Diff</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800">
                {data.games.map((game, idx) => {
                  const isWin = game.result === "WIN";
                  const date = new Date(game.game_date);
                  return (
                    <tr key={idx} className="hover:bg-gray-800/50">
                      <td className="py-3 text-sm">
                        {date.toLocaleDateString(undefined, {
                          month: "short",
                          day: "numeric",
                          year: "numeric",
                        })}
                      </td>
                      <td className="py-3">
                        <span
                          className={`rounded px-2 py-1 text-xs font-bold ${
                            isWin
                              ? "bg-green-600 text-white"
                              : "bg-red-600 text-white"
                          }`}
                        >
                          {game.result}
                        </span>
                      </td>
                      <td className="py-3 text-right font-mono text-sm">
                        {game.team_score?.toFixed(0) ?? "—"}
                      </td>
                      <td className="py-3 text-right font-mono text-sm">
                        {game.opponent_score?.toFixed(0) ?? "—"}
                      </td>
                      <td className="py-3 text-right">
                        <span
                          className={`font-mono text-sm ${
                            game.point_differential >= 0
                              ? "text-green-400"
                              : "text-red-400"
                          }`}
                        >
                          {game.point_differential >= 0 ? "+" : ""}
                          {game.point_differential.toFixed(0)}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {data.total_games > data.page_size && (
            <div className="flex items-center justify-between border-t border-gray-800 pt-4">
              <p className="text-sm text-gray-400">
                Page {data.page} of{" "}
                {Math.ceil(data.total_games / data.page_size)}
              </p>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => onPageChange?.(data.page - 1)}
                  disabled={data.page === 1}
                  className="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-sm disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-700"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                <button
                  onClick={() => onPageChange?.(data.page + 1)}
                  disabled={
                    data.page >= Math.ceil(data.total_games / data.page_size)
                  }
                  className="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-sm disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-700"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          )}
        </>
      ) : (
        <div className="py-8 text-center">
          <p className="text-gray-400">No games found</p>
          <p className="text-sm text-gray-500 mt-1">
            Try adjusting your filters
          </p>
        </div>
      )}
    </div>
  );
}
