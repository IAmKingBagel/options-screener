export interface HealthResponse {
  status: string;
  service: string;
  phase: string;
}

export interface OptionContract {
  symbol: string;
  underlying_symbol: string;
  underlying_price: number | null;
  contract_type: "call" | "put";
  expiration_date: string;
  strike: number;
  dte: number;
  bid: number | null;
  ask: number | null;
  mid: number | null;
  spread_abs: number | null;
  spread_pct: number | null;
  volume: number | null;
  open_interest: number | null;
  implied_volatility: number | null;
  delta: number | null;
  gamma: number | null;
  theta: number | null;
  vega: number | null;
  moneyness: number | null;
  liquidity_score: number | null;
  quote_age_minutes: number | null;
  passes_liquidity: boolean;
  contract_warnings: string[];
}

export interface OptionChainResponse {
  underlying_symbol: string;
  underlying_price: number | null;
  fetched_at: string;
  provider: string;
  snapshot_id: number | null;
  from_cache: boolean;
  contract_count: number;
  liquid_contract_count: number | null;
  rejected_contract_count: number | null;
  warnings: string[];
  contracts: OptionContract[];
}

export interface VolatilityMetrics {
  symbol: string;
  as_of: string;
  underlying_price: number | null;
  realized_vol_10d: number | null;
  realized_vol_20d: number | null;
  realized_vol_30d: number | null;
  realized_vol_60d: number | null;
  forecast_rv_30d: number | null;
  iv30: number | null;
  atm_iv_points: [number, number][];
  iv_rank_52w: number | null;
  iv_percentile_52w: number | null;
  iv_history_count: number;
  iv_history_status: string;
  iv_regime: string;
  vrp: number | null;
  vrp_z: number | null;
  vol_score_short: number | null;
  vol_score_long: number | null;
  warnings: string[];
  notes: string[];
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

async function readApiError(response: Response, fallback: string): Promise<string> {
  const text = await response.text();
  if (!text) return `${fallback}: ${response.status}`;
  try {
    const parsed = JSON.parse(text) as { detail?: unknown };
    if (typeof parsed.detail === "string") return parsed.detail;
  } catch {
    // not JSON — use raw text
  }
  return text;
}

export async function fetchHealth(): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE}/health`);
  if (!response.ok) {
    throw new Error(await readApiError(response, "Health check failed"));
  }
  return response.json();
}

export async function fetchChain(
  symbol: string,
  params?: {
    min_dte?: number;
    max_dte?: number;
    force_refresh?: boolean;
    include_rejected?: boolean;
    sort_by_liquidity?: boolean;
  },
): Promise<OptionChainResponse> {
  const search = new URLSearchParams();
  if (params?.min_dte !== undefined) search.set("min_dte", String(params.min_dte));
  if (params?.max_dte !== undefined) search.set("max_dte", String(params.max_dte));
  if (params?.force_refresh) search.set("force_refresh", "true");
  if (params?.include_rejected) search.set("include_rejected", "true");
  if (params?.sort_by_liquidity === false) search.set("sort_by_liquidity", "false");

  const query = search.toString();
  const url = `${API_BASE}/api/chain/${encodeURIComponent(symbol)}${query ? `?${query}` : ""}`;
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(await readApiError(response, "Chain fetch failed"));
  }
  return response.json();
}

export async function fetchVolatility(
  symbol: string,
  params?: { force_refresh?: boolean },
): Promise<VolatilityMetrics> {
  const search = new URLSearchParams();
  if (params?.force_refresh) search.set("force_refresh", "true");
  const query = search.toString();
  const url = `${API_BASE}/api/volatility/${encodeURIComponent(symbol)}${query ? `?${query}` : ""}`;
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(await readApiError(response, "Volatility fetch failed"));
  }
  return response.json();
}

export interface OptionLeg {
  contract_symbol: string;
  action: "buy" | "sell";
  quantity: number;
  contract_type: "call" | "put";
  strike: number;
  expiration_date: string;
  bid: number | null;
  ask: number | null;
  mid: number | null;
  price_used: number;
  delta: number | null;
  gamma: number | null;
  theta: number | null;
  vega: number | null;
  implied_volatility: number | null;
  open_interest: number | null;
}

export interface StrategyCandidate {
  strategy_id: string;
  underlying_symbol: string;
  underlying_price: number | null;
  strategy_type: string;
  expiration_date: string;
  dte: number;
  legs: OptionLeg[];
  legs_summary: string;
  net_debit_or_credit: number;
  is_credit: boolean;
  mid_net: number | null;
  max_profit: number | null;
  max_loss: number | null;
  breakevens: number[];
  credit_to_width: number | null;
  width: number | null;
  liquidity_score: number;
  greek_summary: Record<string, number>;
  ev_physical: number | null;
  ev_risk_neutral: number | null;
  pop_physical: number | null;
  pop_risk_neutral: number | null;
  alpha: number | null;
  payoff_curve: { price: number; payoff: number }[];
  greek_score: number | null;
  score_breakdown: Record<string, string | number>;
  final_score: number | null;
  grade: string | null;
  scoring_profile: string | null;
  warnings: string[];
  explanation: string;
}

export interface ScreenResponse {
  candidates: StrategyCandidate[];
  warnings: string[];
  symbols_scanned: string[];
}

export interface CandidateMark {
  id: number;
  marked_at: string;
  days_since_entry: number;
  underlying_price: number | null;
  mark_net: number | null;
  pnl: number | null;
  pnl_pct_of_max_profit: number | null;
  notes: string | null;
}

export interface TrackedCandidate {
  id: number;
  strategy_id: string;
  underlying_symbol: string;
  strategy_type: string;
  expiration_date: string;
  dte_at_entry: number;
  legs: OptionLeg[];
  legs_summary: string;
  entry_net: number;
  is_credit: boolean;
  max_profit: number | null;
  max_loss: number | null;
  entry_underlying_price: number | null;
  entry_alpha: number | null;
  entry_final_score: number | null;
  entry_grade: string | null;
  entry_ev_physical: number | null;
  entry_pop_physical: number | null;
  entry_liquidity_score: number | null;
  score_breakdown: Record<string, string | number>;
  explanation: string | null;
  status: string;
  tracked_at: string;
  closed_at: string | null;
  close_reason: string | null;
  latest_pnl: number | null;
  latest_mark_net: number | null;
  latest_underlying_price: number | null;
  latest_marked_at: string | null;
  pnl_1d: number | null;
  pnl_3d: number | null;
  pnl_7d: number | null;
  pnl_14d: number | null;
  hit_50pct_profit: boolean;
  hit_max_loss: boolean;
  marks: CandidateMark[];
  score_vs_outcome: string | null;
}

export interface TrackedListResponse {
  open: TrackedCandidate[];
  closed: TrackedCandidate[];
  summary: {
    open_count: number;
    closed_count: number;
    closed_avg_pnl: number | null;
    closed_win_rate: number | null;
  };
}

export async function trackCandidate(
  candidate: StrategyCandidate,
): Promise<TrackedCandidate> {
  const response = await fetch(`${API_BASE}/api/tracking`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ candidate }),
  });
  if (!response.ok) {
    throw new Error(await readApiError(response, "Track failed"));
  }
  return response.json();
}

export async function listTracked(): Promise<TrackedListResponse> {
  const response = await fetch(`${API_BASE}/api/tracking`);
  if (!response.ok) {
    throw new Error(await readApiError(response, "List tracked failed"));
  }
  return response.json();
}

export async function refreshTracked(id: number): Promise<TrackedCandidate> {
  const response = await fetch(`${API_BASE}/api/tracking/${id}/refresh`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(await readApiError(response, "Refresh failed"));
  }
  return response.json();
}

export async function refreshAllTracked(): Promise<TrackedListResponse> {
  const response = await fetch(`${API_BASE}/api/tracking/refresh-all`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(await readApiError(response, "Refresh all failed"));
  }
  return response.json();
}

export async function closeTracked(id: number): Promise<TrackedCandidate> {
  const response = await fetch(`${API_BASE}/api/tracking/${id}/close`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(await readApiError(response, "Close failed"));
  }
  return response.json();
}

export async function screenStrategies(body: {
  symbols: string[];
  strategy_types?: string[];
  dte_min?: number;
  dte_max?: number;
  force_refresh?: boolean;
}): Promise<ScreenResponse> {
  const response = await fetch(`${API_BASE}/api/screen`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      symbols: body.symbols,
      strategy_types: body.strategy_types,
      dte_min: body.dte_min ?? 14,
      dte_max: body.dte_max ?? 60,
      force_refresh: body.force_refresh ?? false,
      max_candidates_per_strategy: 15,
    }),
  });
  if (!response.ok) {
    throw new Error(await readApiError(response, "Screen failed"));
  }
  return response.json();
}
