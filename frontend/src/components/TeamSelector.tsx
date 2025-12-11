"use client";

import type { NFLTeamInfo } from "@/types/api";

interface TeamSelectorProps {
  teams: NFLTeamInfo[] | undefined;
  selectedTeam: string;
  onTeamChange: (teamSymbol: string) => void;
  isLoading?: boolean;
}

export function TeamSelector({
  teams,
  selectedTeam,
  onTeamChange,
  isLoading,
}: TeamSelectorProps) {
  if (isLoading) {
    return (
      <div className="rounded-lg border border-gray-800 bg-gray-900/40 p-4">
        <div className="animate-pulse space-y-2">
          <div className="h-4 bg-gray-800 rounded w-24" />
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            {[...Array(8)].map((_, i) => (
              <div key={i} className="h-12 bg-gray-800 rounded" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (!teams || teams.length === 0) {
    return (
      <div className="rounded-lg border border-gray-800 bg-gray-900/40 p-4 text-center">
        <p className="text-gray-400">No teams available</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900/40 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-300">Select Team</h3>
        <span className="text-xs text-gray-500">{teams.length} teams</span>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        {teams.map((team) => {
          const isActive = selectedTeam === team.symbol;
          return (
            <button
              key={team.symbol}
              onClick={() => onTeamChange(team.symbol)}
              className={`rounded-lg border p-3 text-left transition-all ${
                isActive
                  ? "border-blue-500 bg-blue-500/10"
                  : "border-gray-700 bg-gray-800/50 hover:border-gray-600 hover:bg-gray-800"
              }`}
            >
              <div className="flex items-start justify-between">
                <div>
                  <p
                    className={`text-sm font-bold ${
                      isActive ? "text-blue-400" : "text-gray-300"
                    }`}
                  >
                    {team.abbreviation}
                  </p>
                  <p className="text-xs text-gray-500 mt-0.5">
                    {team.total_games} games
                  </p>
                </div>
                {isActive && (
                  <div className="h-2 w-2 rounded-full bg-blue-500" />
                )}
              </div>
              <p className="text-xs text-gray-400 mt-1 truncate">
                {team.display_name}
              </p>
            </button>
          );
        })}
      </div>
    </div>
  );
}
