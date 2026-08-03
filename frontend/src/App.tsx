import { useEffect, useMemo, useRef, useState } from "react";
import {
  closeTracked,
  fetchChain,
  fetchHealth,
  fetchVolatility,
  listTracked,
  refreshAllTracked,
  refreshTracked,
  screenStrategies,
  trackCandidate,
  type OptionChainResponse,
  type OptionLeg,
  type StrategyCandidate,
  type TrackedCandidate,
  type TrackedListResponse,
  type VolatilityMetrics,
} from "./api/client";

const DELAY_WARNING =
  "Data may be delayed. Use this dashboard for screening and research, not live execution. Confirm live prices in your brokerage platform before trading.";

type SortKey =
  | "liquidity_score"
  | "spread_pct"
  | "open_interest"
  | "dte"
  | "strike";

function formatPct(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

function formatVol(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

function formatScore(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toFixed(1);
}

function warningClass(warnings: string[]): string {
  if (warnings.some((w) => w.includes("Very wide") || w.includes("No bid"))) {
    return "text-red-300";
  }
  if (warnings.length > 0) {
    return "text-amber-300";
  }
  return "text-slate-500";
}

function formatExpiration(iso: string): string {
  const date = new Date(`${iso}T12:00:00`);
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function formatRelativeTime(iso: string | null): string {
  if (!iso) return "never";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const diffMin = Math.round((Date.now() - then) / 60000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.round(diffHr / 24);
  return `${diffDay}d ago`;
}

function pnlClass(value: number | null | undefined): string {
  if (value === null || value === undefined) return "text-slate-500";
  return value >= 0 ? "text-emerald-400" : "text-red-400";
}

function formatLegRobinhood(leg: OptionLeg, underlying: string): string {
  const optionType = leg.contract_type === "call" ? "Call" : "Put";
  const action = leg.action === "buy" ? "Buy" : "Sell";
  const qty = leg.quantity > 1 ? `${leg.quantity}× ` : "";
  return `${action} ${qty}${underlying} $${leg.strike} ${optionType}`;
}

function LegsRobinhoodList({
  legs,
  underlying,
  expiration,
}: {
  legs: OptionLeg[];
  underlying: string;
  expiration: string;
}) {
  if (!legs.length) {
    return <span className="text-slate-500">—</span>;
  }

  return (
    <ul className="space-y-1 text-xs">
      {legs.map((leg) => (
        <li key={`${leg.contract_symbol}-${leg.action}`} className="font-mono text-slate-200">
          {formatLegRobinhood(leg, underlying)}
          <span className="ml-1 text-slate-500">· {formatExpiration(leg.expiration_date || expiration)}</span>
        </li>
      ))}
    </ul>
  );
}

export default function App() {
  const [health, setHealth] = useState<string>("checking...");
  const [symbol, setSymbol] = useState("SPY");
  const [chain, setChain] = useState<OptionChainResponse | null>(null);
  const [vol, setVol] = useState<VolatilityMetrics | null>(null);
  const [candidates, setCandidates] = useState<StrategyCandidate[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [screenWarnings, setScreenWarnings] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [screening, setScreening] = useState(false);
  const [tracked, setTracked] = useState<TrackedListResponse | null>(null);
  const [trackMessage, setTrackMessage] = useState<string | null>(null);
  const detailRef = useRef<HTMLDivElement | null>(null);

  async function loadTracked() {
    try {
      setTracked(await listTracked());
    } catch {
      // Tracking panel is optional if backend is mid-reload.
    }
  }

  useEffect(() => {
    loadTracked();
  }, []);
  const [includeRejected, setIncludeRejected] = useState(false);
  const [sortKey, setSortKey] = useState<SortKey>("liquidity_score");
  const [sortDesc, setSortDesc] = useState(true);

  useEffect(() => {
    fetchHealth()
      .then((data) => setHealth(`${data.status} (${data.service}, phase ${data.phase})`))
      .catch(() => setHealth("offline"));
  }, []);

  useEffect(() => {
    if (!selectedId || !detailRef.current) return;
    detailRef.current.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [selectedId]);

  async function runScreen(ticker: string, forceRefresh = false) {
    setScreening(true);
    try {
      const result = await screenStrategies({
        symbols: [ticker],
        force_refresh: forceRefresh,
      });
      setCandidates(result.candidates);
      setSelectedId(result.candidates[0]?.strategy_id ?? null);
      setScreenWarnings(result.warnings);
    } catch (err) {
      setCandidates([]);
      setSelectedId(null);
      setScreenWarnings([]);
      setError(err instanceof Error ? err.message : "Screen failed");
    } finally {
      setScreening(false);
    }
  }

  function selectCandidate(strategyId: string) {
    setSelectedId(strategyId);
    setTrackMessage(null);
  }

  async function handleFetch(forceRefresh = false) {
    setLoading(true);
    setError(null);
    setTrackMessage(null);
    const ticker = symbol.trim().toUpperCase();
    try {
      const [data, volData] = await Promise.all([
        fetchChain(ticker, {
          min_dte: 14,
          max_dte: 60,
          force_refresh: forceRefresh,
          include_rejected: includeRejected,
          sort_by_liquidity: sortKey === "liquidity_score",
        }),
        fetchVolatility(ticker, { force_refresh: forceRefresh }),
      ]);
      setChain(data);
      setVol(volData);
      await runScreen(ticker, forceRefresh);
    } catch (err) {
      setChain(null);
      setVol(null);
      setCandidates([]);
      setSelectedId(null);
      setError(err instanceof Error ? err.message : "Failed to fetch data");
    } finally {
      setLoading(false);
    }
  }

  const sortedContracts = useMemo(() => {
    if (!chain) return [];
    const rows = [...chain.contracts];
    rows.sort((a, b) => {
      const av = a[sortKey] ?? -Infinity;
      const bv = b[sortKey] ?? -Infinity;
      if (av === bv) return 0;
      return sortDesc ? (bv > av ? 1 : -1) : (av > bv ? 1 : -1);
    });
    return rows;
  }, [chain, sortKey, sortDesc]);

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDesc((value) => !value);
    } else {
      setSortKey(key);
      setSortDesc(true);
    }
  }

  function sortIndicator(key: SortKey): string {
    if (sortKey !== key) return "";
    return sortDesc ? " ↓" : " ↑";
  }

  return (
    <div className="mx-auto max-w-7xl px-4 py-8">
      <header className="mb-8">
        <h1 className="text-3xl font-semibold tracking-tight">Options Screener</h1>
        <p className="mt-2 text-slate-400">
          Swing-trade candidate discovery · API health:{" "}
          <span className="font-mono text-emerald-400">{health}</span>
        </p>
      </header>

      <div className="mb-6 rounded-lg border border-amber-500/40 bg-amber-500/10 p-4 text-sm text-amber-100">
        {DELAY_WARNING}
      </div>

      <section className="mb-8 flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-sm text-slate-300">
          Symbol
          <input
            className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 font-mono uppercase"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            placeholder="SPY"
          />
        </label>
        <label className="flex items-center gap-2 text-sm text-slate-300">
          <input
            type="checkbox"
            checked={includeRejected}
            onChange={(e) => setIncludeRejected(e.target.checked)}
          />
          Show rejected contracts
        </label>
        <button
          type="button"
          onClick={() => handleFetch(false)}
          disabled={loading || screening || !symbol.trim()}
          className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium hover:bg-emerald-500 disabled:opacity-50"
        >
          {loading || screening ? "Loading..." : "Fetch chain + screen"}
        </button>
        <button
          type="button"
          onClick={() => handleFetch(true)}
          disabled={loading || screening || !symbol.trim()}
          className="rounded-md border border-slate-600 px-4 py-2 text-sm hover:bg-slate-900 disabled:opacity-50"
        >
          Force refresh
        </button>
        <button
          type="button"
          onClick={() => runScreen(symbol.trim().toUpperCase(), false)}
          disabled={screening || loading || !symbol.trim() || !chain}
          className="rounded-md bg-sky-600 px-4 py-2 text-sm font-medium hover:bg-sky-500 disabled:opacity-50"
        >
          {screening ? "Screening..." : "Re-screen only"}
        </button>
      </section>

      {error && (
        <div className="mb-6 rounded-lg border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-200">
          {error}
        </div>
      )}

      {trackMessage && (
        <div className="mb-4 text-sm text-emerald-400">{trackMessage}</div>
      )}

      {chain && (
        <section className="space-y-4">
          <div className="flex flex-wrap gap-4 text-sm text-slate-300">
            <span>
              Underlying: <strong className="text-white">{chain.underlying_symbol}</strong>
            </span>
            <span>
              Price:{" "}
              <strong className="text-white">
                {chain.underlying_price?.toFixed(2) ?? "—"}
              </strong>
            </span>
            <span>
              Showing: <strong className="text-white">{chain.contract_count}</strong>
            </span>
            {chain.liquid_contract_count != null && (
              <span>
                Liquid: <strong className="text-emerald-400">{chain.liquid_contract_count}</strong>
              </span>
            )}
            {chain.rejected_contract_count != null && chain.rejected_contract_count > 0 && (
              <span>
                Rejected:{" "}
                <strong className="text-amber-400">{chain.rejected_contract_count}</strong>
              </span>
            )}
            <span>
              Source:{" "}
              <strong className="text-white">
                {chain.from_cache ? "cache" : "live fetch"}
              </strong>
            </span>
          </div>

          {chain.warnings.length > 0 && (
            <ul className="list-disc space-y-1 pl-5 text-sm text-slate-400">
              {chain.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          )}

          {vol && (
            <section className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
              <h2 className="mb-3 text-lg font-medium text-white">
                Volatility context — {vol.symbol}
              </h2>
              <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
                <Metric label="IV30" value={formatVol(vol.iv30)} />
                <Metric label="Forecast RV30" value={formatVol(vol.forecast_rv_30d)} />
                <Metric label="RV10" value={formatVol(vol.realized_vol_10d)} />
                <Metric label="RV20" value={formatVol(vol.realized_vol_20d)} />
                <Metric label="RV30" value={formatVol(vol.realized_vol_30d)} />
                <Metric label="RV60" value={formatVol(vol.realized_vol_60d)} />
                <Metric label="VRP" value={vol.vrp?.toFixed(4) ?? "—"} />
                <Metric label="VRP z" value={vol.vrp_z?.toFixed(2) ?? "—"} />
                <Metric label="IV Rank" value={formatScore(vol.iv_rank_52w)} />
                <Metric label="IV Percentile" value={formatScore(vol.iv_percentile_52w)} />
                <Metric label="Short-vol score" value={formatScore(vol.vol_score_short)} />
                <Metric label="Long-vol score" value={formatScore(vol.vol_score_long)} />
              </div>
              <div className="mt-3 flex flex-wrap gap-3 text-xs text-slate-400">
                <span>
                  Regime:{" "}
                  <strong className="text-slate-200">{vol.iv_regime}</strong>
                </span>
                <span>
                  IV history:{" "}
                  <strong className="text-slate-200">
                    {vol.iv_history_status} ({vol.iv_history_count} days)
                  </strong>
                </span>
              </div>
              {vol.notes.length > 0 && (
                <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-slate-400">
                  {vol.notes.map((note) => (
                    <li key={note}>{note}</li>
                  ))}
                </ul>
              )}
            </section>
          )}

          <div className="overflow-x-auto rounded-lg border border-slate-800">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-900 text-slate-300">
                <tr>
                  <th className="px-3 py-2">Status</th>
                  <th
                    className="cursor-pointer px-3 py-2 hover:text-white"
                    onClick={() => toggleSort("liquidity_score")}
                  >
                    Liq{sortIndicator("liquidity_score")}
                  </th>
                  <th className="px-3 py-2">Type</th>
                  <th
                    className="cursor-pointer px-3 py-2 hover:text-white"
                    onClick={() => toggleSort("strike")}
                  >
                    Strike{sortIndicator("strike")}
                  </th>
                  <th
                    className="cursor-pointer px-3 py-2 hover:text-white"
                    onClick={() => toggleSort("dte")}
                  >
                    DTE{sortIndicator("dte")}
                  </th>
                  <th className="px-3 py-2">Bid</th>
                  <th className="px-3 py-2">Ask</th>
                  <th className="px-3 py-2">Mid</th>
                  <th
                    className="cursor-pointer px-3 py-2 hover:text-white"
                    onClick={() => toggleSort("spread_pct")}
                  >
                    Spread %{sortIndicator("spread_pct")}
                  </th>
                  <th
                    className="cursor-pointer px-3 py-2 hover:text-white"
                    onClick={() => toggleSort("open_interest")}
                  >
                    OI{sortIndicator("open_interest")}
                  </th>
                  <th className="px-3 py-2">Moneyness</th>
                  <th className="px-3 py-2">Warnings</th>
                </tr>
              </thead>
              <tbody>
                {sortedContracts.slice(0, 150).map((contract) => (
                  <tr
                    key={contract.symbol}
                    className={`border-t border-slate-800 ${
                      contract.passes_liquidity === false ? "bg-red-950/20" : ""
                    }`}
                  >
                    <td className="px-3 py-2">
                      {contract.passes_liquidity ? (
                        <span className="text-emerald-400">OK</span>
                      ) : (
                        <span className="text-red-400">Reject</span>
                      )}
                    </td>
                    <td className="px-3 py-2 font-mono">
                      {contract.liquidity_score?.toFixed(1) ?? "—"}
                    </td>
                    <td className="px-3 py-2 uppercase">{contract.contract_type}</td>
                    <td className="px-3 py-2 font-mono">{contract.strike}</td>
                    <td className="px-3 py-2">{contract.dte}</td>
                    <td className="px-3 py-2 font-mono">{contract.bid ?? "—"}</td>
                    <td className="px-3 py-2 font-mono">{contract.ask ?? "—"}</td>
                    <td className="px-3 py-2 font-mono">{contract.mid?.toFixed(2) ?? "—"}</td>
                    <td className="px-3 py-2">{formatPct(contract.spread_pct)}</td>
                    <td className="px-3 py-2">{contract.open_interest ?? "—"}</td>
                    <td className="px-3 py-2 font-mono">
                      {contract.moneyness?.toFixed(3) ?? "—"}
                    </td>
                    <td className={`px-3 py-2 text-xs ${warningClass(contract.contract_warnings)}`}>
                      {contract.contract_warnings.length > 0
                        ? contract.contract_warnings.join("; ")
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {sortedContracts.length > 150 && (
              <p className="border-t border-slate-800 px-3 py-2 text-xs text-slate-500">
                Showing first 150 of {sortedContracts.length} contracts.
              </p>
            )}
          </div>
        </section>
      )}

      {(screening || candidates.length > 0) && (
        <section className="mb-8 space-y-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-lg font-medium text-white">
              Strategy candidates
              {candidates.length > 0 ? ` (${candidates.length})` : ""}
            </h2>
            <p className="text-xs text-slate-400">
              Click a row to open detail and track. Contract rows above are not clickable.
            </p>
          </div>
          {screening && candidates.length === 0 && (
            <p className="text-sm text-slate-400">Building strategy candidates...</p>
          )}
          {screenWarnings.length > 0 && (
            <ul className="list-disc space-y-1 pl-5 text-xs text-slate-400">
              {screenWarnings.slice(0, 4).map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          )}
          {candidates.length > 0 && (
            <div className="overflow-x-auto rounded-lg border border-slate-800">
              <table className="min-w-full text-left text-sm">
                <thead className="bg-slate-900 text-slate-300">
                  <tr>
                    <th className="px-3 py-2">Grade</th>
                    <th className="px-3 py-2">Score</th>
                    <th className="px-3 py-2">Type</th>
                    <th className="px-3 py-2">Legs</th>
                    <th className="px-3 py-2">DTE</th>
                    <th className="px-3 py-2">Net</th>
                    <th className="px-3 py-2">EV</th>
                    <th className="px-3 py-2">Alpha</th>
                    <th className="px-3 py-2">Greek</th>
                    <th className="px-3 py-2">Liq</th>
                    <th className="px-3 py-2">Warnings</th>
                  </tr>
                </thead>
                <tbody>
                  {candidates.slice(0, 50).map((c) => {
                    const selected = selectedId === c.strategy_id;
                    return (
                      <tr
                        key={c.strategy_id}
                        role="button"
                        tabIndex={0}
                        aria-selected={selected}
                        className={`cursor-pointer border-t border-slate-800 align-top transition-colors hover:bg-slate-900/80 focus:outline-none focus:ring-2 focus:ring-emerald-500/60 ${
                          selected
                            ? "bg-emerald-950/40 ring-1 ring-emerald-500/50"
                            : ""
                        }`}
                        onClick={() => selectCandidate(c.strategy_id)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            selectCandidate(c.strategy_id);
                          }
                        }}
                      >
                        <td className="px-3 py-2 font-semibold text-emerald-300">
                          {c.grade ?? "—"}
                        </td>
                        <td className="px-3 py-2 font-mono">
                          {c.final_score?.toFixed(1) ?? "—"}
                        </td>
                        <td className="px-3 py-2 font-mono text-xs">{c.strategy_type}</td>
                        <td className="px-3 py-2 font-mono text-xs">{c.legs_summary}</td>
                        <td className="px-3 py-2">{c.dte}</td>
                        <td className="px-3 py-2 font-mono">
                          {c.is_credit ? "+" : "-"}
                          {c.net_debit_or_credit?.toFixed(2) ?? "—"}
                        </td>
                        <td
                          className={`px-3 py-2 font-mono ${
                            (c.ev_physical ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"
                          }`}
                        >
                          {c.ev_physical?.toFixed(3) ?? "—"}
                        </td>
                        <td
                          className={`px-3 py-2 font-mono font-medium ${
                            (c.alpha ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"
                          }`}
                        >
                          {c.alpha?.toFixed(3) ?? "—"}
                        </td>
                        <td className="px-3 py-2 font-mono">
                          {c.greek_score?.toFixed(1) ?? "—"}
                        </td>
                        <td className="px-3 py-2">
                          {c.liquidity_score?.toFixed(1) ?? "—"}
                        </td>
                        <td className="px-3 py-2 text-xs text-amber-300">
                          {c.warnings.length ? c.warnings.slice(0, 2).join("; ") : "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <div ref={detailRef}>
            {selectedId && (
              <CandidateDetail
                candidate={candidates.find((c) => c.strategy_id === selectedId) ?? null}
                onTrack={async (candidate) => {
                  try {
                    await trackCandidate(candidate);
                    setTrackMessage(`Tracked ${candidate.legs_summary}`);
                    setError(null);
                    await loadTracked();
                  } catch (err) {
                    setError(err instanceof Error ? err.message : "Track failed");
                  }
                }}
              />
            )}
          </div>
        </section>
      )}

      <TrackedPanel
        tracked={tracked}
        onRefreshAll={async () => {
          try {
            setTracked(await refreshAllTracked());
          } catch (err) {
            setError(err instanceof Error ? err.message : "Refresh failed");
          }
        }}
        onRefreshOne={async (id) => {
          try {
            await refreshTracked(id);
            await loadTracked();
          } catch (err) {
            setError(err instanceof Error ? err.message : "Refresh failed");
          }
        }}
        onClose={async (id) => {
          try {
            await closeTracked(id);
            await loadTracked();
          } catch (err) {
            setError(err instanceof Error ? err.message : "Close failed");
          }
        }}
      />
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-950/60 px-3 py-2">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="font-mono text-sm text-white">{value}</div>
    </div>
  );
}

function CandidateDetail({
  candidate,
  onTrack,
}: {
  candidate: StrategyCandidate | null;
  onTrack: (candidate: StrategyCandidate) => void;
}) {
  if (!candidate) return null;
  const curve = candidate.payoff_curve ?? [];
  let path = "";
  if (curve.length > 1) {
    const xs = curve.map((p) => p.price);
    const ys = curve.map((p) => p.payoff);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    const w = 480;
    const h = 140;
    const pad = 8;
    const scaleX = (x: number) =>
      pad + ((x - minX) / Math.max(maxX - minX, 1e-6)) * (w - 2 * pad);
    const scaleY = (y: number) =>
      h - pad - ((y - minY) / Math.max(maxY - minY, 1e-6)) * (h - 2 * pad);
    path = curve
      .map((p, i) => `${i === 0 ? "M" : "L"} ${scaleX(p.price)} ${scaleY(p.payoff)}`)
      .join(" ");
  }

  return (
    <div className="rounded-lg border border-emerald-500/40 bg-slate-900/60 p-4 shadow-lg shadow-emerald-950/20">
      <h3 className="mb-2 text-sm font-medium text-white">
        Detail — Grade {candidate.grade ?? "—"} ({candidate.final_score?.toFixed(1) ?? "—"})
        {" · "}
        {candidate.strategy_type} · {candidate.legs_summary}
      </h3>
      {candidate.legs?.length > 0 && (
        <div className="mb-3 rounded-md border border-slate-800 bg-slate-950/60 p-3">
          <div className="mb-2 text-xs font-medium text-slate-400">
            Contracts (look up on Robinhood)
          </div>
          <div className="mb-2 text-sm font-semibold text-white">
            {candidate.underlying_symbol} · {formatExpiration(candidate.expiration_date)}
          </div>
          <LegsRobinhoodList
            legs={candidate.legs}
            underlying={candidate.underlying_symbol}
            expiration={candidate.expiration_date}
          />
        </div>
      )}
      <p className="mb-3 text-xs text-slate-300">{candidate.explanation}</p>
      <div className="mb-3 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4 lg:grid-cols-6">
        <Metric label="EV physical" value={candidate.ev_physical?.toFixed(3) ?? "—"} />
        <Metric label="EV risk-neutral" value={candidate.ev_risk_neutral?.toFixed(3) ?? "—"} />
        <Metric
          label="POP physical"
          value={
            candidate.pop_physical != null
              ? `${(candidate.pop_physical * 100).toFixed(1)}%`
              : "—"
          }
        />
        <Metric label="Alpha" value={candidate.alpha?.toFixed(3) ?? "—"} />
        <Metric label="Greek score" value={candidate.greek_score?.toFixed(1) ?? "—"} />
        <Metric label="Profile" value={candidate.scoring_profile ?? "—"} />
      </div>
      {candidate.score_breakdown && Object.keys(candidate.score_breakdown).length > 0 && (
        <div className="mb-3">
          <div className="mb-1 text-xs font-medium text-slate-400">Score breakdown</div>
          <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
            {Object.entries(candidate.score_breakdown).map(([key, value]) => (
              <Metric key={key} label={key} value={String(value)} />
            ))}
          </div>
        </div>
      )}
      {path && (
        <svg viewBox="0 0 480 140" className="w-full max-w-xl rounded bg-slate-950">
          <path d={path} fill="none" stroke="#34d399" strokeWidth="2" />
        </svg>
      )}
      <p className="mt-2 text-xs text-slate-500">
        Payoff at expiration (per share). Alpha = EV_physical / max_loss. Not financial advice.
      </p>
      <button
        type="button"
        onClick={() => onTrack(candidate)}
        className="mt-3 rounded-md bg-violet-600 px-3 py-1.5 text-xs font-medium hover:bg-violet-500"
      >
        Track this candidate
      </button>
    </div>
  );
}

function TrackedPanel({
  tracked,
  onRefreshAll,
  onRefreshOne,
  onClose,
}: {
  tracked: TrackedListResponse | null;
  onRefreshAll: () => Promise<void> | void;
  onRefreshOne: (id: number) => Promise<void> | void;
  onClose: (id: number) => Promise<void> | void;
}) {
  const open = tracked?.open ?? [];
  const closed = tracked?.closed ?? [];
  const summary = tracked?.summary;
  const [refreshingAll, setRefreshingAll] = useState(false);
  const [refreshingId, setRefreshingId] = useState<number | null>(null);

  return (
    <section className="mb-8 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-medium text-white">Tracked candidates</h2>
        <button
          type="button"
          disabled={refreshingAll || open.length === 0}
          onClick={async () => {
            setRefreshingAll(true);
            try {
              await onRefreshAll();
            } finally {
              setRefreshingAll(false);
            }
          }}
          className="rounded-md border border-slate-600 px-3 py-1.5 text-xs hover:bg-slate-900 disabled:opacity-50"
        >
          {refreshingAll ? "Refreshing..." : "Refresh open marks"}
        </button>
      </div>
      <p className="text-xs text-slate-500">
        P/L is modeled mark-to-market from delayed data (per share; ×100 per contract),
        not broker fills. Marks update only when you click Refresh — nothing updates
        automatically. The 1d / 7d / 14d columns snapshot on the first refresh after
        those days pass. Expired positions settle at intrinsic value and auto-close.
      </p>
      {summary && (
        <div className="flex flex-wrap gap-4 text-xs text-slate-400">
          <span>
            Open: <strong className="text-white">{summary.open_count}</strong>
          </span>
          <span>
            Closed: <strong className="text-white">{summary.closed_count}</strong>
          </span>
          {summary.closed_avg_pnl != null && (
            <span>
              Closed avg P/L:{" "}
              <strong className="text-white">{summary.closed_avg_pnl.toFixed(3)}</strong>
            </span>
          )}
          {summary.closed_win_rate != null && (
            <span>
              Win rate:{" "}
              <strong className="text-white">
                {(summary.closed_win_rate * 100).toFixed(0)}%
              </strong>
            </span>
          )}
        </div>
      )}
      {open.length === 0 && closed.length === 0 ? (
        <p className="text-sm text-slate-500">
          No tracked candidates yet. Screen strategies, open a detail row, then click
          Track.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-800">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-900 text-slate-300">
              <tr>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Stock</th>
                <th className="px-3 py-2">Expiration</th>
                <th className="px-3 py-2">Contracts</th>
                <th className="px-3 py-2">Strategy</th>
                <th className="px-3 py-2">Grade</th>
                <th className="px-3 py-2">Entry</th>
                <th className="px-3 py-2">Latest P/L</th>
                <th className="px-3 py-2">Marked</th>
                <th className="px-3 py-2">1d / 7d / 14d</th>
                <th className="px-3 py-2">Score vs outcome</th>
                <th className="px-3 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {[...open, ...closed].map((row: TrackedCandidate) => (
                <tr key={row.id} className="border-t border-slate-800 align-top">
                  <td className="px-3 py-2 text-xs uppercase">{row.status}</td>
                  <td className="px-3 py-2 font-mono font-semibold text-white">
                    {row.underlying_symbol}
                  </td>
                  <td className="px-3 py-2 font-mono text-xs whitespace-nowrap">
                    {formatExpiration(row.expiration_date)}
                  </td>
                  <td className="px-3 py-2 min-w-[220px]">
                    <LegsRobinhoodList
                      legs={row.legs ?? []}
                      underlying={row.underlying_symbol}
                      expiration={row.expiration_date}
                    />
                  </td>
                  <td className="px-3 py-2 font-mono text-xs">{row.strategy_type}</td>
                  <td className="px-3 py-2">{row.entry_grade ?? "—"}</td>
                  <td className="px-3 py-2 font-mono">{row.entry_net.toFixed(2)}</td>
                  <td className={`px-3 py-2 font-mono ${pnlClass(row.latest_pnl)}`}>
                    {row.latest_pnl?.toFixed(3) ?? "—"}
                  </td>
                  <td className="px-3 py-2 text-xs whitespace-nowrap text-slate-400">
                    {formatRelativeTime(row.latest_marked_at)}
                  </td>
                  <td className="px-3 py-2 font-mono text-xs">
                    {row.pnl_1d?.toFixed(2) ?? "—"} / {row.pnl_7d?.toFixed(2) ?? "—"} /{" "}
                    {row.pnl_14d?.toFixed(2) ?? "—"}
                  </td>
                  <td className="px-3 py-2 text-xs text-slate-400">
                    {row.score_vs_outcome ?? "—"}
                  </td>
                  <td className="px-3 py-2">
                    {row.status === "open" ? (
                      <div className="flex gap-2">
                        <button
                          type="button"
                          disabled={refreshingId === row.id}
                          className="text-xs text-sky-400 hover:underline disabled:opacity-50"
                          onClick={async () => {
                            setRefreshingId(row.id);
                            try {
                              await onRefreshOne(row.id);
                            } finally {
                              setRefreshingId(null);
                            }
                          }}
                        >
                          {refreshingId === row.id ? "..." : "Refresh"}
                        </button>
                        <button
                          type="button"
                          className="text-xs text-amber-400 hover:underline"
                          onClick={() => onClose(row.id)}
                        >
                          Close
                        </button>
                      </div>
                    ) : (
                      <span className="text-xs text-slate-500">
                        {row.close_reason ?? "closed"}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
