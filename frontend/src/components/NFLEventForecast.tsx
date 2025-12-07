import { TrendingUp, Calendar, Users, Sparkles, Info } from "lucide-react";
import type { NFLTeamForecast } from "@/types/api";

interface NFLEventForecastProps {
  forecast: NFLTeamForecast | undefined;
  isLoading: boolean;
}

export function NFLEventForecast({
  forecast,
  isLoading,
}: NFLEventForecastProps) {
  if (isLoading) {
    return (
      <div className="animate-pulse space-y-3 rounded-xl border border-gray-700 bg-gray-800/50 p-5">
        <div className="h-6 w-48 rounded bg-gray-700" />
        <div className="h-20 rounded bg-gray-700" />
      </div>
    );
  }

  if (!forecast || !forecast.next_game_found) {
    return (
      <div className="rounded-xl border border-gray-700 bg-gray-800/50 p-5">
        <div className="flex items-start gap-3">
          <Info className="h-5 w-5 text-gray-400" />
          <div>
            <h3 className="font-semibold text-gray-300">No Upcoming Game</h3>
            <p className="mt-1 text-sm text-gray-500">
              {forecast?.message || "No scheduled games found in the next 30 days."}
            </p>
          </div>
        </div>
      </div>
    );
  }

  const hasEventForecasts = forecast.event_forecasts_count > 0;
  const winProb = forecast.aggregated_win_probability;
  const confidence = forecast.forecast_confidence;

  // Format game date
  const gameDate = forecast.game_date ? new Date(forecast.game_date) : null;
  const daysUntil = forecast.days_until_game?.toFixed(1);

  // Win probability color
  const getWinProbColor = (prob: number) => {
    if (prob >= 0.6) return "text-green-400";
    if (prob >= 0.5) return "text-yellow-400";
    return "text-red-400";
  };

  return (
    <div className="space-y-4 rounded-xl border border-purple-500/30 bg-purple-500/10 p-5">
      {/* Header */}
      <div className="flex items-center gap-2">
        <Sparkles className="h-5 w-5 text-purple-400" />
        <h3 className="font-semibold text-purple-300">
          Event-Based Forecast
        </h3>
        <span className="rounded bg-purple-500/20 px-2 py-0.5 text-xs text-purple-300">
          AI-Powered
        </span>
      </div>

      {/* Next Game Info */}
      <div className="space-y-2 rounded-lg border border-purple-500/20 bg-purple-500/5 p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Calendar className="h-4 w-4 text-purple-400" />
            <span className="text-sm font-medium text-purple-200">
              Next Game
            </span>
          </div>
          <div className="text-right">
            {gameDate && (
              <div className="text-sm font-semibold text-purple-100">
                {gameDate.toLocaleDateString("en-US", {
                  month: "short",
                  day: "numeric",
                  year: "numeric",
                })}
              </div>
            )}
            {daysUntil && (
              <div className="text-xs text-purple-400">
                {daysUntil} days away
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center justify-between">
          <span className="text-sm text-gray-400">Opponent</span>
          <span className="text-sm font-semibold text-purple-100">
            {forecast.opponent || "TBD"}
          </span>
        </div>
      </div>

      {/* Win Probability */}
      {hasEventForecasts && winProb !== null ? (
        <div className="space-y-3">
          <div className="flex items-center justify-between rounded-lg border border-purple-500/20 bg-purple-500/5 p-4">
            <div className="flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-purple-400" />
              <span className="text-sm font-medium text-purple-200">
                Win Probability
              </span>
            </div>
            <div className="text-right">
              <div className={`text-2xl font-bold ${getWinProbColor(winProb)}`}>
                {(winProb * 100).toFixed(1)}%
              </div>
              {confidence !== null && (
                <div className="text-xs text-gray-400">
                  {(confidence * 100).toFixed(0)}% confidence
                </div>
              )}
            </div>
          </div>

          {/* Event Forecasts */}
          {forecast.event_forecasts && forecast.event_forecasts.length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <Users className="h-4 w-4 text-purple-400" />
                <span className="text-xs font-medium text-purple-300">
                  Contributing Events ({forecast.event_forecasts.length})
                </span>
              </div>
              <div className="max-h-48 space-y-2 overflow-y-auto">
                {forecast.event_forecasts.map((evt) => (
                  <div
                    key={evt.event_id}
                    className="rounded-lg border border-purple-500/20 bg-purple-500/5 p-3"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-xs font-medium text-purple-100">
                          {evt.event_title}
                        </p>
                        <p className="mt-0.5 text-xs text-gray-400">
                          {new Date(evt.event_date).toLocaleDateString()}
                        </p>
                      </div>
                      <div className="text-right">
                        <div
                          className={`text-sm font-semibold ${getWinProbColor(evt.win_probability)}`}
                        >
                          {(evt.win_probability * 100).toFixed(0)}%
                        </div>
                        <div className="text-xs text-gray-500">
                          {evt.similar_events} similar
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="rounded-lg border border-purple-500/20 bg-purple-500/5 p-4">
          <div className="flex items-start gap-2">
            <Info className="h-4 w-4 text-purple-400" />
            <div>
              <p className="text-sm font-medium text-purple-200">
                Awaiting Events
              </p>
              <p className="mt-1 text-xs text-gray-400">
                Event-based predictions will appear as sports news is ingested.
                RSS feeds run hourly to capture team-relevant events.
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
