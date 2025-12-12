"use client";

import { useState, useMemo } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  ReferenceDot,
  TooltipProps,
} from "recharts";
import { TrendingUp, TrendingDown, Circle, Calendar } from "lucide-react";
import type { ForecastTimeline } from "@/types/api";

interface ForecastTimelineProps {
  data: ForecastTimeline | undefined;
  isLoading: boolean;
}

type TimeRange = "7d" | "30d" | "90d";

interface ChartDataPoint {
  timestamp: string;
  date: Date;
  ml_model?: number;
  baker_api?: number;
  event_weighted?: number;
  event?: {
    id: string;
    title: string;
    impact: number;
  };
}

interface VisibleLines {
  ml_model: boolean;
  baker_api: boolean;
  event_weighted: boolean;
}

export function ForecastTimeline({ data, isLoading }: ForecastTimelineProps) {
  const [timeRange, setTimeRange] = useState<TimeRange>("30d");
  const [visibleLines, setVisibleLines] = useState<VisibleLines>({
    ml_model: true,
    baker_api: true,
    event_weighted: true,
  });

  // Transform data for Recharts
  const chartData = useMemo(() => {
    if (!data?.timeline) return [];

    const now = new Date();
    const daysBack = timeRange === "7d" ? 7 : timeRange === "30d" ? 30 : 90;
    const cutoffDate = new Date(now.getTime() - daysBack * 24 * 60 * 60 * 1000);

    return data.timeline
      .map((point): ChartDataPoint => {
        const date = new Date(point.timestamp);
        return {
          timestamp: point.timestamp,
          date,
          ml_model: point.forecasts.ml_model_v2
            ? point.forecasts.ml_model_v2.value * 100
            : undefined,
          baker_api: point.forecasts.baker_api
            ? point.forecasts.baker_api.value * 100
            : undefined,
          event_weighted: point.forecasts.event_weighted
            ? point.forecasts.event_weighted.value * 100
            : undefined,
          event: point.event,
        };
      })
      .filter((point) => point.date >= cutoffDate)
      .sort((a, b) => a.date.getTime() - b.date.getTime());
  }, [data, timeRange]);

  // Custom tooltip
  const CustomTooltip = ({
    active,
    payload,
  }: any) => {
    if (!active || !payload || payload.length === 0) return null;

    const data = payload[0].payload as ChartDataPoint;
    const date = new Date(data.timestamp);

    // Find previous point for delta calculation
    const currentIndex = chartData.findIndex(
      (p) => p.timestamp === data.timestamp
    );
    const previousPoint =
      currentIndex > 0 ? chartData[currentIndex - 1] : null;

    const calculateDelta = (
      current: number | undefined,
      previous: number | undefined
    ) => {
      if (current === undefined || previous === undefined) return null;
      return current - previous;
    };

    return (
      <div className="rounded-lg border border-gray-600 bg-gray-800/95 p-3 shadow-lg backdrop-blur-sm">
        <div className="flex items-center gap-2 border-b border-gray-600 pb-2 mb-2">
          <Calendar className="h-3 w-3 text-gray-400" />
          <p className="text-xs font-semibold text-gray-200">
            {date.toLocaleDateString("en-US", {
              month: "short",
              day: "numeric",
              year: "numeric",
            })}
          </p>
        </div>

        <div className="space-y-1.5">
          {data.ml_model !== undefined && visibleLines.ml_model && (
            <div className="flex items-center justify-between gap-4">
              <div className="flex items-center gap-1.5">
                <div className="h-2 w-2 rounded-full bg-blue-400" />
                <span className="text-xs text-gray-300">ML Model</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-blue-400">
                  {data.ml_model.toFixed(1)}%
                </span>
                {previousPoint?.ml_model !== undefined && (
                  <DeltaIndicator
                    delta={calculateDelta(data.ml_model, previousPoint.ml_model)}
                  />
                )}
              </div>
            </div>
          )}

          {data.baker_api !== undefined && visibleLines.baker_api && (
            <div className="flex items-center justify-between gap-4">
              <div className="flex items-center gap-1.5">
                <div className="h-2 w-2 rounded-full bg-green-400" />
                <span className="text-xs text-gray-300">Baker API</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-green-400">
                  {data.baker_api.toFixed(1)}%
                </span>
                {previousPoint?.baker_api !== undefined && (
                  <DeltaIndicator
                    delta={calculateDelta(data.baker_api, previousPoint.baker_api)}
                  />
                )}
              </div>
            </div>
          )}

          {data.event_weighted !== undefined && visibleLines.event_weighted && (
            <div className="flex items-center justify-between gap-4">
              <div className="flex items-center gap-1.5">
                <div className="h-2 w-2 rounded-full bg-purple-400" />
                <span className="text-xs text-gray-300">Event-Weighted</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-purple-400">
                  {data.event_weighted.toFixed(1)}%
                </span>
                {previousPoint?.event_weighted !== undefined && (
                  <DeltaIndicator
                    delta={calculateDelta(
                      data.event_weighted,
                      previousPoint.event_weighted
                    )}
                  />
                )}
              </div>
            </div>
          )}
        </div>

        {data.event && (
          <div className="mt-2 border-t border-gray-600 pt-2">
            <div className="flex items-start gap-1.5">
              <Circle
                className={`h-3 w-3 mt-0.5 ${
                  data.event.impact > 0
                    ? "text-green-400 fill-green-400"
                    : data.event.impact < 0
                    ? "text-red-400 fill-red-400"
                    : "text-gray-400 fill-gray-400"
                }`}
              />
              <div className="flex-1">
                <p className="text-xs font-medium text-gray-200">
                  {data.event.title}
                </p>
                <p className="text-xs text-gray-400 mt-0.5">
                  Impact: {data.event.impact > 0 ? "+" : ""}
                  {(data.event.impact * 100).toFixed(1)}%
                </p>
              </div>
            </div>
          </div>
        )}
      </div>
    );
  };

  const toggleLine = (line: keyof VisibleLines) => {
    setVisibleLines((prev) => ({ ...prev, [line]: !prev[line] }));
  };

  if (isLoading) {
    return (
      <div className="space-y-4 rounded-xl border border-gray-700 bg-gray-800/50 p-6">
        <div className="animate-pulse space-y-3">
          <div className="h-6 w-48 rounded bg-gray-700" />
          <div className="h-64 rounded bg-gray-700" />
        </div>
      </div>
    );
  }

  if (!data || !chartData || chartData.length === 0) {
    return (
      <div className="rounded-xl border border-gray-700 bg-gray-800/50 p-6 text-center">
        <TrendingUp className="mx-auto h-12 w-12 text-gray-600" />
        <h3 className="mt-3 font-semibold text-gray-300">
          No forecast history available
        </h3>
        <p className="mt-1 text-sm text-gray-500">
          Forecast data will appear here as the system generates predictions
          over time.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4 rounded-xl border border-gray-700 bg-gray-800/50 p-6">
      {/* Header with time range selector */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold text-gray-200">
            Win Probability Timeline
          </h3>
          <p className="text-sm text-gray-400">
            Historical forecast evolution with event markers
          </p>
        </div>
        <div className="flex gap-1 rounded-lg border border-gray-600 bg-gray-700/50 p-1">
          {(["7d", "30d", "90d"] as TimeRange[]).map((range) => (
            <button
              key={range}
              onClick={() => setTimeRange(range)}
              className={`rounded px-3 py-1 text-xs font-medium transition-colors ${
                timeRange === range
                  ? "bg-blue-500 text-white"
                  : "text-gray-400 hover:text-gray-200"
              }`}
            >
              {range}
            </button>
          ))}
        </div>
      </div>

      {/* Chart */}
      <div className="h-80">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={chartData}
            margin={{ top: 5, right: 30, left: 0, bottom: 5 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
            <XAxis
              dataKey="timestamp"
              stroke="#9CA3AF"
              tick={{ fill: "#9CA3AF", fontSize: 12 }}
              tickFormatter={(value) => {
                const date = new Date(value);
                return date.toLocaleDateString("en-US", {
                  month: "short",
                  day: "numeric",
                });
              }}
            />
            <YAxis
              stroke="#9CA3AF"
              tick={{ fill: "#9CA3AF", fontSize: 12 }}
              domain={[0, 100]}
              label={{
                value: "Win Probability (%)",
                angle: -90,
                position: "insideLeft",
                style: { fill: "#9CA3AF", fontSize: 12 },
              }}
            />
            <Tooltip content={<CustomTooltip />} />
            <Legend
              wrapperStyle={{ paddingTop: "20px" }}
              content={<CustomLegend visible={visibleLines} onToggle={toggleLine} />}
            />

            {visibleLines.ml_model && (
              <Line
                type="monotone"
                dataKey="ml_model"
                stroke="#60A5FA"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 6 }}
                name="ML Model v2.0"
                connectNulls
              />
            )}

            {visibleLines.baker_api && (
              <Line
                type="monotone"
                dataKey="baker_api"
                stroke="#34D399"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 6 }}
                name="Baker API"
                connectNulls
              />
            )}

            {visibleLines.event_weighted && (
              <Line
                type="monotone"
                dataKey="event_weighted"
                stroke="#A78BFA"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 6 }}
                name="Event-Weighted"
                connectNulls
              />
            )}

            {/* Event markers */}
            {chartData.map((point, index) => {
              if (!point.event) return null;
              const impact = point.event.impact;
              const color =
                impact > 0 ? "#34D399" : impact < 0 ? "#F87171" : "#9CA3AF";

              return (
                <ReferenceDot
                  key={`event-${index}`}
                  x={point.timestamp}
                  y={point.ml_model || point.baker_api || point.event_weighted || 50}
                  r={Math.abs(impact) * 50 + 3}
                  fill={color}
                  fillOpacity={0.6}
                  stroke={color}
                  strokeWidth={2}
                />
              );
            })}
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Event markers legend */}
      <div className="flex items-center gap-6 rounded-lg border border-gray-600 bg-gray-700/30 p-3 text-xs">
        <span className="font-medium text-gray-300">Event Impact:</span>
        <div className="flex items-center gap-1.5">
          <Circle className="h-3 w-3 fill-green-400 text-green-400" />
          <span className="text-gray-400">Positive</span>
        </div>
        <div className="flex items-center gap-1.5">
          <Circle className="h-3 w-3 fill-red-400 text-red-400" />
          <span className="text-gray-400">Negative</span>
        </div>
        <div className="flex items-center gap-1.5">
          <Circle className="h-3 w-3 fill-gray-400 text-gray-400" />
          <span className="text-gray-400">Neutral</span>
        </div>
        <span className="text-gray-500">
          (Size indicates magnitude)
        </span>
      </div>
    </div>
  );
}

// Helper component for delta indicators
function DeltaIndicator({ delta }: { delta: number | null }) {
  if (delta === null) return null;

  const isPositive = delta > 0;
  const isNeutral = Math.abs(delta) < 0.1;

  if (isNeutral) return null;

  return (
    <span
      className={`flex items-center gap-0.5 text-xs ${
        isPositive ? "text-green-400" : "text-red-400"
      }`}
    >
      {isPositive ? (
        <TrendingUp className="h-3 w-3" />
      ) : (
        <TrendingDown className="h-3 w-3" />
      )}
      {isPositive ? "+" : ""}
      {delta.toFixed(1)}%
    </span>
  );
}

// Custom legend component with toggle functionality
function CustomLegend({
  visible,
  onToggle,
}: {
  visible: VisibleLines;
  onToggle: (line: keyof VisibleLines) => void;
}) {
  const legendItems: Array<{
    key: keyof VisibleLines;
    label: string;
    color: string;
    description: string;
  }> = [
    {
      key: "ml_model",
      label: "ML Model v2.0",
      color: "bg-blue-400",
      description: "Logistic regression (58.8% accuracy)",
    },
    {
      key: "baker_api",
      label: "Baker API",
      color: "bg-green-400",
      description: "External projection data",
    },
    {
      key: "event_weighted",
      label: "Event-Weighted",
      color: "bg-purple-400",
      description: "Semantic event-based forecast",
    },
  ];

  return (
    <div className="flex flex-wrap items-center justify-center gap-4 pt-2">
      {legendItems.map((item) => (
        <button
          key={item.key}
          onClick={() => onToggle(item.key)}
          className={`flex items-center gap-2 rounded-lg border px-3 py-2 transition-all ${
            visible[item.key]
              ? "border-gray-600 bg-gray-700/50"
              : "border-gray-700 bg-gray-800/30 opacity-50"
          } hover:border-gray-500`}
        >
          <div className={`h-3 w-3 rounded-full ${item.color}`} />
          <div className="text-left">
            <p className="text-xs font-medium text-gray-200">{item.label}</p>
            <p className="text-xs text-gray-500">{item.description}</p>
          </div>
        </button>
      ))}
    </div>
  );
}
