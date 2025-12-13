"use client";

import { AlertTriangle, CheckCircle2, AlertCircle } from "lucide-react";

interface ConfidenceBadgeProps {
  sampleSize: number;
  confidence: number;
  showLabel?: boolean;
  size?: "sm" | "md" | "lg";
}

type ConfidenceLevel = "high" | "medium" | "low";

interface ConfidenceConfig {
  level: ConfidenceLevel;
  color: string;
  bgColor: string;
  borderColor: string;
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  message: string;
}

function getConfidenceLevel(
  sampleSize: number,
  confidence: number
): ConfidenceConfig {
  // Traffic light rules from PLAN_MAESTRO:
  // GREEN: sample_size >= 20 AND confidence > 0.6
  // YELLOW: sample_size >= 8 OR confidence 0.4-0.6
  // RED: sample_size < 8 OR confidence < 0.4

  if (sampleSize >= 20 && confidence > 0.6) {
    return {
      level: "high",
      color: "text-green-400",
      bgColor: "bg-green-500/10",
      borderColor: "border-green-500/30",
      icon: CheckCircle2,
      label: "High Confidence",
      message: "Strong historical signal",
    };
  }

  if (sampleSize < 8 || confidence < 0.4) {
    return {
      level: "low",
      color: "text-red-400",
      bgColor: "bg-red-500/10",
      borderColor: "border-red-500/30",
      icon: AlertTriangle,
      label: "Low Confidence",
      message: "Insufficient data - use caution",
    };
  }

  return {
    level: "medium",
    color: "text-yellow-400",
    bgColor: "bg-yellow-500/10",
    borderColor: "border-yellow-500/30",
    icon: AlertCircle,
    label: "Moderate Confidence",
    message: "Limited historical data",
  };
}

export function ConfidenceBadge({
  sampleSize,
  confidence,
  showLabel = true,
  size = "md",
}: ConfidenceBadgeProps) {
  const config = getConfidenceLevel(sampleSize, confidence);
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

  return (
    <div
      className={`inline-flex items-center gap-2 rounded-lg border px-3 py-1.5 ${config.bgColor} ${config.borderColor}`}
    >
      <Icon className={`${iconSizes[size]} ${config.color}`} />
      {showLabel && (
        <div className="flex flex-col">
          <span className={`${textSizes[size]} font-medium ${config.color}`}>
            {config.label}
          </span>
          <span className="text-xs text-gray-500">{config.message}</span>
        </div>
      )}
    </div>
  );
}

// Compact version for inline use
export function ConfidenceIndicator({
  sampleSize,
  confidence,
}: {
  sampleSize: number;
  confidence: number;
}) {
  const config = getConfidenceLevel(sampleSize, confidence);
  const Icon = config.icon;

  return (
    <div className="flex items-center gap-1.5">
      <Icon className={`h-3.5 w-3.5 ${config.color}`} />
      <span className={`text-xs font-medium ${config.color}`}>
        {config.level.toUpperCase()}
      </span>
    </div>
  );
}
