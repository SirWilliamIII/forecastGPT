"use client";

import { TrendingUp, TrendingDown, Activity, Wind } from "lucide-react";

interface RegimeBadgeProps {
  regime: string;
  size?: "sm" | "md" | "lg";
}

type RegimeType = "uptrend" | "downtrend" | "chop" | "high_vol";

interface RegimeConfig {
  type: RegimeType;
  label: string;
  color: string;
  bgColor: string;
  borderColor: string;
  icon: React.ComponentType<{ className?: string }>;
  description: string;
}

function getRegimeConfig(regime: string): RegimeConfig {
  const normalized = regime.toLowerCase() as RegimeType;

  const configs: Record<RegimeType, RegimeConfig> = {
    uptrend: {
      type: "uptrend",
      label: "Uptrend",
      color: "text-green-400",
      bgColor: "bg-green-500/10",
      borderColor: "border-green-500/30",
      icon: TrendingUp,
      description: "Bullish momentum",
    },
    downtrend: {
      type: "downtrend",
      label: "Downtrend",
      color: "text-red-400",
      bgColor: "bg-red-500/10",
      borderColor: "border-red-500/30",
      icon: TrendingDown,
      description: "Bearish momentum",
    },
    chop: {
      type: "chop",
      label: "Choppy",
      color: "text-yellow-400",
      bgColor: "bg-yellow-500/10",
      borderColor: "border-yellow-500/30",
      icon: Activity,
      description: "Sideways movement",
    },
    high_vol: {
      type: "high_vol",
      label: "High Volatility",
      color: "text-orange-400",
      bgColor: "bg-orange-500/10",
      borderColor: "border-orange-500/30",
      icon: Wind,
      description: "Elevated uncertainty",
    },
  };

  return (
    configs[normalized] || {
      type: "chop",
      label: regime,
      color: "text-gray-400",
      bgColor: "bg-gray-500/10",
      borderColor: "border-gray-500/30",
      icon: Activity,
      description: "Unknown regime",
    }
  );
}

export function RegimeBadge({ regime, size = "md" }: RegimeBadgeProps) {
  const config = getRegimeConfig(regime);
  const Icon = config.icon;

  const iconSizes = {
    sm: "h-3 w-3",
    md: "h-4 w-4",
    lg: "h-5 w-5",
  };

  const textSizes = {
    sm: "text-xs",
    md: "text-sm",
    lg: "text-base",
  };

  const paddingSizes = {
    sm: "px-2 py-0.5",
    md: "px-3 py-1",
    lg: "px-4 py-1.5",
  };

  return (
    <div
      className={`inline-flex items-center gap-1.5 rounded-lg border ${paddingSizes[size]} ${config.bgColor} ${config.borderColor}`}
    >
      <Icon className={`${iconSizes[size]} ${config.color}`} />
      <span className={`${textSizes[size]} font-medium ${config.color}`}>
        {config.label}
      </span>
    </div>
  );
}

// Compact version with tooltip
export function RegimeIndicator({ regime }: { regime: string }) {
  const config = getRegimeConfig(regime);
  const Icon = config.icon;

  return (
    <div
      className="group relative inline-flex items-center gap-1"
      title={config.description}
    >
      <Icon className={`h-3.5 w-3.5 ${config.color}`} />
      <span className={`text-xs font-medium ${config.color}`}>
        {config.label}
      </span>
      <div className="pointer-events-none absolute bottom-full left-1/2 mb-2 hidden -translate-x-1/2 whitespace-nowrap rounded bg-gray-900 px-2 py-1 text-xs text-gray-300 group-hover:block">
        {config.description}
      </div>
    </div>
  );
}
