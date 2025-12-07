// frontend/src/lib/api.ts

import type {
  AssetForecast,
  EventSummary,
  SimilarEventsResponse,
  EventReturnForecast,
  EventAnalysis,
  HealthCheck,
  Projection,
  NFLTeamForecast,
} from "@/types/api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:9000";

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  if (!response.ok) {
    throw new Error(`API error: ${response.status} ${response.statusText}`);
  }

  return response.json();
}

// Health
export async function getHealth(): Promise<HealthCheck> {
  return fetchJson<HealthCheck>(`${API_BASE}/health`);
}

// Event domains
export type EventDomain = "crypto" | "sports" | "tech" | "general";

// Events
export async function getRecentEvents(
  limit = 50,
  source?: string,
  domain?: EventDomain
): Promise<EventSummary[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (source) params.set("source", source);
  if (domain) params.set("domain", domain);
  return fetchJson<EventSummary[]>(`${API_BASE}/events/recent?${params}`);
}

export async function getSimilarEvents(
  eventId: string,
  limit = 10
): Promise<SimilarEventsResponse> {
  const params = new URLSearchParams({ limit: String(limit) });
  return fetchJson<SimilarEventsResponse>(
    `${API_BASE}/events/${eventId}/similar?${params}`
  );
}

// Forecasts
export async function getAssetForecast(
  symbol: string,
  horizonMinutes = 1440,
  lookbackDays = 60
): Promise<AssetForecast> {
  const params = new URLSearchParams({
    symbol,
    horizon_minutes: String(horizonMinutes),
    lookback_days: String(lookbackDays),
  });
  return fetchJson<AssetForecast>(`${API_BASE}/forecast/asset?${params}`);
}

export async function getEventForecast(
  eventId: string,
  symbol: string,
  horizonMinutes = 1440
): Promise<EventReturnForecast> {
  const params = new URLSearchParams({
    symbol,
    horizon_minutes: String(horizonMinutes),
  });
  return fetchJson<EventReturnForecast>(
    `${API_BASE}/forecast/event/${eventId}?${params}`
  );
}

// Analysis
export async function analyzeEvent(
  eventId: string,
  symbol = "BTC-USD",
  provider = "claude"
): Promise<EventAnalysis> {
  const params = new URLSearchParams({ symbol, provider });
  return fetchJson<EventAnalysis>(
    `${API_BASE}/analyze/event/${eventId}?${params}`
  );
}

// Projections (e.g., Baker win probabilities)
export async function getLatestProjections(
  symbol: string,
  metric = "win_prob",
  limit = 5
): Promise<Projection[]> {
  const params = new URLSearchParams({
    symbol,
    metric,
    limit: String(limit),
  });
  return fetchJson<Projection[]>(`${API_BASE}/projections/latest?${params}`);
}

export async function getProjectionTeams(): Promise<Record<string, string>> {
  return fetchJson<Record<string, string>>(`${API_BASE}/projections/teams`);
}

// NFL Event-Based Forecasting
export async function getNFLTeamForecast(
  teamSymbol: string,
  includeRecentEvents = true
): Promise<NFLTeamForecast> {
  const params = new URLSearchParams({
    include_recent_events: String(includeRecentEvents),
  });
  return fetchJson<NFLTeamForecast>(
    `${API_BASE}/forecast/nfl/team/${teamSymbol}/next-game?${params}`
  );
}

// Dynamic discovery endpoints
export interface AvailableSymbols {
  all: string[];
  crypto: string[];
  equity: string[];
}

export interface AvailableHorizon {
  value: number;
  label: string;
  available: boolean;
}

export interface AvailableSource {
  value: string;
  label: string;
  count: number;
}

export async function getAvailableSymbols(): Promise<AvailableSymbols> {
  return fetchJson<AvailableSymbols>(`${API_BASE}/symbols/available`);
}

export async function getAvailableHorizons(): Promise<AvailableHorizon[]> {
  return fetchJson<AvailableHorizon[]>(`${API_BASE}/horizons/available`);
}

export async function getAvailableSources(): Promise<AvailableSource[]> {
  return fetchJson<AvailableSource[]>(`${API_BASE}/sources/available`);
}
