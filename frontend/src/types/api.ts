// frontend/src/types/api.ts

export interface AssetForecast {
  symbol: string;
  as_of: string;
  horizon_minutes: number;
  expected_return: number | null;
  direction: string | null;
  confidence: number;
  lookback_days: number;
  n_points: number;
  mean_return: number | null;
  vol_return: number | null;
  features: Record<string, unknown>;
}

export interface EventSummary {
  id: string;
  timestamp: string;
  source: string;
  url: string | null;
  title: string;
  summary: string;
  categories: string[];
  tags: string[];
}

export interface EventNeighbor {
  id: string;
  timestamp: string | null;
  source: string;
  url: string | null;
  raw_text: string;
  categories: string[];
  tags: string[];
  distance: number;
}

export interface SimilarEventsResponse {
  event_id: string;
  neighbors: EventNeighbor[];
}

export interface EventReturnForecast {
  event_id: string;
  symbol: string;
  horizon_minutes: number;
  expected_return: number;
  std_return: number;
  p_up: number;
  p_down: number;
  sample_size: number;
  neighbors_used: number;
}

export interface EventAnalysis {
  event_id: string;
  sentiment: string;
  impact_score: number;
  confidence: number;
  reasoning: string;
  tags: string[];
  provider: string;
}

export interface HealthCheck {
  status: string;
  database: string;
  pgvector: string;
}

export interface Projection {
  symbol: string;
  as_of: string;
  horizon_minutes: number;
  metric: string;
  projected_value: number;
  model_source: string;
  game_id?: number;
  run_id?: string;
  opponent?: string;
  opponent_name?: string;
  meta?: Record<string, unknown>;
}

// Domain configuration - extensible to any target type
export type TargetDomain = "crypto" | "sports" | "equities" | "custom";

export interface TargetConfig {
  id: string;
  label: string;
  domain: TargetDomain;
  color: string;
}

// Current crypto symbols (extensible)
export const CRYPTO_SYMBOLS = ["BTC-USD", "ETH-USD", "XMR-USD"] as const;
export type CryptoSymbol = (typeof CRYPTO_SYMBOLS)[number];

// For backward compatibility
export const SYMBOLS = CRYPTO_SYMBOLS;
export type Symbol = CryptoSymbol;

// Horizons with data availability
// Currently only 24h has training data; others are placeholders for future expansion
export const HORIZONS = [
  { value: 1440, label: "24 hours", available: true },
  { value: 60, label: "1 hour", available: false },
  { value: 10080, label: "1 week", available: false },
] as const;

// NFL Event-Based Forecasting
export interface NFLEventForecast {
  event_id: string;
  event_title: string;
  event_date: string;
  win_probability: number;
  confidence: number;
  similar_events: number;
}

export interface NFLTeamForecast {
  team_symbol: string;
  next_game_found: boolean;
  game_date: string | null;
  days_until_game: number | null;
  opponent: string | null;
  event_forecasts_count: number;
  event_forecasts?: NFLEventForecast[];
  aggregated_win_probability: number | null;
  forecast_confidence: number | null;
  message: string | null;
}
