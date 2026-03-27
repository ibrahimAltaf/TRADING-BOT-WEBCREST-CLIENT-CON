import { useState } from "react";
import {
  useBalancesQuery,
  useKlinesQuery,
  useTickerPriceQuery,
  useDecisionLatestQuery,
  useDecisionsRecentQuery,
  useLogsRecentQuery,
  useAllOrdersQuery,
  useTradesQuery,
  usePositionsOpenQuery,
  usePerformanceSummaryQuery,
  useCancelOrderMutation,
  useProofQuery,
} from "../../apis/exchange/useExchangeQueries";
import PriceChart from "../../components/charts/PriceChart";
import OrdersTable from "../../components/exchange/OrdersTable";
import TradesTable from "../../components/exchange/TradesTable";
import type { TradingDecision } from "../../apis/exchange/exchange.api";

function fmtNum(value: number | null | undefined, digits = 2) {
  if (value == null || !Number.isFinite(value)) return "—";
  return value.toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  });
}

const INTERVALS = ["1m", "5m", "15m", "1h", "4h", "1d"] as const;
type TableTab = "orders" | "trades";
type InfoTab = "decisions" | "logs";

export default function ExchangeMonitor() {
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [interval, setInterval] = useState("1h");
  const [tableTab, setTableTab] = useState<TableTab>("orders");
  const [infoTab, setInfoTab] = useState<InfoTab>("decisions");
  const [cancelLoadingOrderId, setCancelLoadingOrderId] = useState<
    number | null
  >(null);

  const cancelOrder = useCancelOrderMutation({
    onMutate: (v) => setCancelLoadingOrderId(v.order_id),
    onSettled: () => setCancelLoadingOrderId(null),
  });

  const balances = useBalancesQuery();
  const ticker = useTickerPriceQuery(symbol);
  const klines = useKlinesQuery(symbol, interval, 100);
  const decisionLatest = useDecisionLatestQuery(symbol);
  const decisionsRecent = useDecisionsRecentQuery({ symbol, limit: 15 });
  const logs = useLogsRecentQuery({ limit: 30 });
  const allOrders = useAllOrdersQuery(symbol, 50);
  const trades = useTradesQuery({ symbol, limit: 50 });
  const positions = usePositionsOpenQuery();
  const performanceSummary = usePerformanceSummaryQuery("live");
  const proof = useProofQuery(symbol);

  const price = ticker.data?.price;
  const balanceList = (balances.data?.balances ?? [])
    .map((b) => ({
      asset: b.asset,
      free: b.free,
      locked: b.locked,
      total: b.total ?? String(Number(b.free) + Number(b.locked)),
    }))
    .filter((b) => Number(b.total) > 0);

  const orders = allOrders.data?.orders ?? [];
  const tradesList = trades.data?.trades ?? [];
  const positionsList =
    positions.data?.positions ?? positions.data?.items ?? [];
  const decisions = decisionsRecent.data?.decisions ?? [];
  const logItems = (logs.data as any)?.items ?? (logs.data as any)?.logs ?? [];
  const perf = performanceSummary.data;
  const latestDecision = decisionLatest.data?.decision;

  return (
    <div className="space-y-4">
      {/* ── Top bar: symbol + intervals + live price ── */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={symbol}
            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            className="h-9 w-28 rounded-lg border border-slate-200 bg-slate-50 px-3 text-sm font-bold uppercase text-slate-800 focus:border-slate-400 focus:outline-none"
          />
          <div className="flex items-center gap-0.5 rounded-lg border border-slate-200 bg-slate-50 p-1">
            {INTERVALS.map((i) => (
              <button
                key={i}
                onClick={() => setInterval(i)}
                className={`rounded-md px-2.5 py-1 text-xs font-semibold transition-colors ${
                  interval === i
                    ? "bg-white text-slate-900 shadow-sm border border-slate-200"
                    : "text-slate-400 hover:text-slate-600"
                }`}
              >
                {i}
              </button>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-4">
          <div className="flex items-baseline gap-2">
            <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">
              Price
            </span>
            <span className="text-xl font-bold tabular-nums text-slate-900">
              {ticker.isLoading
                ? "…"
                : price != null
                  ? `$${fmtNum(price, 2)}`
                  : "—"}
            </span>
          </div>
          <div className="flex items-center gap-1.5 text-xs text-slate-400">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
            Live
          </div>
        </div>
      </div>

      {/* ── Chart ── */}
      <PriceChart
        data={klines.data?.klines ?? []}
        symbol={symbol}
        interval={interval}
        height={360}
        loading={klines.isFetching}
      />

      {/* ── Performance strip ── */}
      <div className="grid grid-cols-2 gap-px sm:grid-cols-4 rounded-xl border border-slate-200 bg-slate-100 shadow-sm overflow-hidden">
        <PerfStat
          label="Total PnL"
          loading={performanceSummary.isLoading}
          value={
            perf?.total_pnl_usdt != null ? (
              <span
                className={
                  perf.total_pnl_usdt >= 0
                    ? "text-emerald-600"
                    : "text-rose-600"
                }
              >
                {perf.total_pnl_usdt >= 0 ? "+" : "−"}$
                {Math.abs(perf.total_pnl_usdt).toFixed(2)}
              </span>
            ) : (
              "—"
            )
          }
        />
        <PerfStat
          label="Win Rate"
          loading={performanceSummary.isLoading}
          value={
            perf?.win_rate_pct != null
              ? `${fmtNum(perf.win_rate_pct, 1)}%`
              : "—"
          }
        />
        <PerfStat
          label="Total Trades"
          loading={performanceSummary.isLoading}
          value={perf?.total_trades ?? "—"}
        />
        <PerfStat
          label="Last Signal"
          loading={performanceSummary.isLoading}
          value={
            perf?.last_signal ? (
              <span
                className={
                  perf.last_signal === "BUY"
                    ? "text-emerald-600"
                    : perf.last_signal === "SELL"
                      ? "text-rose-600"
                      : "text-slate-600"
                }
              >
                {perf.last_signal}
              </span>
            ) : (
              "—"
            )
          }
        />
      </div>

      {/* ── Audit proof strip ── */}
      <div className="grid grid-cols-2 gap-px sm:grid-cols-4 rounded-xl border border-slate-200 bg-slate-100 shadow-sm overflow-hidden">
        <PerfStat
          label="Mode"
          loading={proof.isLoading}
          value={
            proof.data?.environment?.binance_testnet
              ? "Paper/Testnet"
              : "Live/Mainnet"
          }
        />
        <PerfStat
          label="USDT Balance"
          loading={proof.isLoading}
          value={
            proof.data?.balances?.usdt
              ? fmtNum(Number(proof.data.balances.usdt.total ?? 0), 2)
              : "—"
          }
        />
        <PerfStat
          label="Open Orders"
          loading={proof.isLoading}
          value={proof.data?.orders?.open_count ?? "—"}
        />
        <PerfStat
          label="Closed PnL (USDT)"
          loading={proof.isLoading}
          value={fmtNum(proof.data?.performance?.realized_pnl_usdt, 2)}
        />
      </div>

      {/* ── 3-col info row ── */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Latest decision */}
        <Card
          title="Latest Decision"
          loading={decisionLatest.isLoading}
          error={decisionLatest.error?.message}
        >
          {!latestDecision ? (
            <p className="text-sm text-slate-400">No decision yet</p>
          ) : (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span
                  className={`text-2xl font-bold ${
                    latestDecision.action === "BUY"
                      ? "text-emerald-600"
                      : latestDecision.action === "SELL"
                        ? "text-rose-600"
                        : "text-slate-500"
                  }`}
                >
                  {latestDecision.action}
                </span>
                <span className="rounded-full bg-slate-100 border border-slate-200 px-2.5 py-0.5 text-xs font-semibold text-slate-600">
                  {latestDecision.regime ?? "—"}
                </span>
              </div>
              <div className="space-y-1.5">
                <InfoRow
                  label="Confidence"
                  value={
                    latestDecision.confidence != null
                      ? `${fmtNum(latestDecision.confidence * 100, 1)}%`
                      : "—"
                  }
                />
                <InfoRow
                  label="Price"
                  value={`$${fmtNum(latestDecision.price, 2)}`}
                />
                <InfoRow
                  label="Executed"
                  value={
                    <span
                      className={
                        latestDecision.executed
                          ? "text-emerald-600"
                          : "text-slate-400"
                      }
                    >
                      {latestDecision.executed ? "Yes" : "No"}
                    </span>
                  }
                />
                <InfoRow
                  label="Order ID"
                  value={latestDecision.order_id ?? "—"}
                />
                <InfoRow
                  label="Rule / ML / Final"
                  value={`${latestDecision.rule_signal ?? "—"} / ${latestDecision.ml_signal ?? "—"} / ${latestDecision.final_action ?? latestDecision.action ?? "—"}`}
                />
                <InfoRow
                  label="Risk-Reward"
                  value={
                    latestDecision.risk?.risk_reward != null
                      ? fmtNum(latestDecision.risk.risk_reward, 2)
                      : "—"
                  }
                />
                <InfoRow
                  label="ADX / RSI"
                  value={`${fmtNum(latestDecision.indicators?.adx, 1)} / ${fmtNum(latestDecision.indicators?.rsi, 1)}`}
                />
              </div>
              <p className="line-clamp-2 rounded-lg bg-slate-50 border border-slate-100 px-3 py-2 text-xs leading-relaxed text-slate-500">
                {latestDecision.reason}
              </p>
            </div>
          )}
        </Card>

        {/* Open positions */}
        <Card
          title="Open Positions"
          loading={positions.isLoading}
          error={positions.error?.message}
          badge={
            positionsList.length > 0 ? String(positionsList.length) : undefined
          }
        >
          {positionsList.length === 0 ? (
            <p className="text-sm text-slate-400">No open positions</p>
          ) : (
            <div className="space-y-2">
              {positionsList.slice(0, 5).map((p: any) => (
                <div
                  key={p.id}
                  className="flex items-center justify-between rounded-lg border border-slate-100 bg-slate-50 px-3 py-2"
                >
                  <div>
                    <div className="text-sm font-bold text-slate-800">
                      {p.symbol}
                    </div>
                    <div className="text-xs text-slate-400">
                      {p.entry_ts
                        ? new Date(p.entry_ts).toLocaleString(undefined, {
                            month: "short",
                            day: "numeric",
                            hour: "2-digit",
                            minute: "2-digit",
                          })
                        : "—"}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-sm font-semibold tabular-nums text-slate-800">
                      ${fmtNum(p.entry_price, 2)}
                    </div>
                    <div className="text-xs text-slate-400 tabular-nums">
                      {fmtNum(p.entry_qty, 5)}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        {/* Balances */}
        <Card
          title="Balances"
          loading={balances.isLoading}
          error={balances.error?.message}
        >
          {balanceList.length === 0 ? (
            <p className="text-sm text-slate-400">No balances</p>
          ) : (
            <div className="space-y-0.5">
              {balanceList.slice(0, 8).map((b) => (
                <div
                  key={b.asset}
                  className="flex items-center justify-between rounded-lg px-2 py-1.5 hover:bg-slate-50 transition-colors"
                >
                  <span className="text-sm font-semibold text-slate-700">
                    {b.asset}
                  </span>
                  <div className="text-right">
                    <div className="text-sm tabular-nums font-medium text-slate-800">
                      {fmtNum(Number(b.total), 4)}
                    </div>
                    {Number(b.locked) > 0 && (
                      <div className="text-xs tabular-nums text-amber-500">
                        {fmtNum(Number(b.locked), 4)} locked
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      {/* ── Orders / Trades tabbed ── */}
      <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
        <div className="flex items-center justify-between border-b border-slate-200 px-4 pt-1">
          <div className="flex">
            {(["orders", "trades"] as TableTab[]).map((tab) => (
              <button
                key={tab}
                onClick={() => setTableTab(tab)}
                className={`flex items-center gap-2 px-4 py-3 text-sm font-semibold border-b-2 transition-colors capitalize ${
                  tableTab === tab
                    ? "border-slate-800 text-slate-900"
                    : "border-transparent text-slate-400 hover:text-slate-600"
                }`}
              >
                {tab === "orders" ? "Orders" : "Trades"}
                <span
                  className={`text-xs rounded-full px-1.5 py-0.5 font-medium ${
                    tableTab === tab
                      ? "bg-slate-100 text-slate-600"
                      : "bg-slate-50 text-slate-400"
                  }`}
                >
                  {tab === "orders" ? orders.length : tradesList.length}
                </span>
              </button>
            ))}
          </div>
          <span className="text-xs font-medium text-slate-400">{symbol}</span>
        </div>
        <div className="max-h-[400px] overflow-y-auto overflow-x-auto">
          <div className="min-w-[700px]">
            {tableTab === "orders" ? (
              <OrdersTable
                orders={orders}
                symbol={symbol}
                loading={allOrders.isLoading}
                maxRows={50}
                showOrderId={true}
                onCancel={(orderId) =>
                  cancelOrder.mutate({ symbol, order_id: orderId })
                }
                cancelLoadingOrderId={cancelLoadingOrderId}
              />
            ) : (
              <TradesTable
                trades={tradesList}
                symbol={symbol}
                loading={trades.isLoading}
                maxRows={50}
              />
            )}
          </div>
        </div>
      </div>

      {/* ── Decisions / Logs tabbed ── */}
      <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
        <div className="flex items-center justify-between border-b border-slate-200 px-4 pt-1">
          <div className="flex">
            {(["decisions", "logs"] as InfoTab[]).map((tab) => (
              <button
                key={tab}
                onClick={() => setInfoTab(tab)}
                className={`flex items-center gap-2 px-4 py-3 text-sm font-semibold border-b-2 transition-colors ${
                  infoTab === tab
                    ? "border-slate-800 text-slate-900"
                    : "border-transparent text-slate-400 hover:text-slate-600"
                }`}
              >
                {tab === "decisions" ? "Recent Decisions" : "System Logs"}
              </button>
            ))}
          </div>
          {(infoTab === "decisions"
            ? decisionsRecent.isFetching
            : logs.isFetching) && (
            <span className="text-xs text-slate-400 animate-pulse">
              Updating…
            </span>
          )}
        </div>

        <div className="max-h-80 overflow-auto p-3">
          {infoTab === "decisions" ? (
            decisions.length === 0 ? (
              <p className="py-6 text-center text-sm text-slate-400">
                No decisions yet
              </p>
            ) : (
              <div className="space-y-1.5">
                {decisions.map((d: TradingDecision) => {
                  const action = d.final_action ?? d.action;

                  return (
                    <div
                      key={d.id}
                      className="rounded-lg border border-slate-100 px-3 py-3 hover:bg-slate-50 transition-colors"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex min-w-0 items-start gap-3">
                          <span
                            className={`min-w-[48px] rounded-md py-0.5 text-center text-xs font-bold ${
                              action === "BUY"
                                ? "bg-emerald-50 text-emerald-600"
                                : action === "SELL"
                                  ? "bg-rose-50 text-rose-600"
                                  : "bg-slate-100 text-slate-500"
                            }`}
                          >
                            {action}
                          </span>

                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                              <span className="text-sm tabular-nums font-medium text-slate-700">
                                {d.price != null
                                  ? `$${fmtNum(d.price, 2)}`
                                  : "—"}
                              </span>

                              <span className="text-xs text-slate-500">
                                {d.symbol} · {d.timeframe}
                              </span>

                              {d.confidence != null && (
                                <span className="text-xs text-slate-500">
                                  Confidence: {(d.confidence * 100).toFixed(0)}%
                                </span>
                              )}
                            </div>

                            {d.reason && (
                              <p className="mt-1.5 text-xs leading-relaxed text-slate-500">
                                {d.reason}
                              </p>
                            )}

                            <div className="mt-2 flex flex-wrap gap-1.5">
                              {d.rule_signal && (
                                <span className="rounded-md bg-blue-50 px-2 py-0.5 text-[11px] font-medium text-blue-700">
                                  Rule: {d.rule_signal}
                                </span>
                              )}

                              {d.ml_signal && (
                                <span className="rounded-md bg-violet-50 px-2 py-0.5 text-[11px] font-medium text-violet-700">
                                  ML: {d.ml_signal}
                                </span>
                              )}

                              {d.ml_confidence != null && (
                                <span className="rounded-md bg-fuchsia-50 px-2 py-0.5 text-[11px] font-medium text-fuchsia-700">
                                  ML Conf: {(d.ml_confidence * 100).toFixed(0)}%
                                </span>
                              )}

                              {d.combined_signal && (
                                <span className="rounded-md bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-700">
                                  Combined: {d.combined_signal}
                                </span>
                              )}

                              {d.risk?.risk_reward != null && (
                                <span className="rounded-md bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-700">
                                  R:R {fmtNum(d.risk.risk_reward, 2)}
                                </span>
                              )}

                              {d.order_id && (
                                <span className="rounded-md bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-700">
                                  Order #{d.order_id}
                                </span>
                              )}

                              {d.executed && (
                                <span className="rounded-md bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700">
                                  Executed
                                </span>
                              )}

                              {!d.executed && (
                                <span className="rounded-md bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600">
                                  Not Executed
                                </span>
                              )}
                            </div>

                            {d.override_reason && (
                              <p className="mt-2 text-[11px] leading-relaxed text-amber-700">
                                Override: {d.override_reason}
                              </p>
                            )}
                          </div>
                        </div>

                        <span className="shrink-0 text-xs text-slate-400">
                          {d.timestamp
                            ? new Date(d.timestamp).toLocaleTimeString()
                            : "—"}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )
          ) : logItems.length === 0 ? (
            <p className="py-6 text-center text-sm text-slate-400">No logs</p>
          ) : (
            <div className="space-y-1 font-mono">
              {logItems.slice(0, 20).map((log: any) => (
                <div
                  key={log.id}
                  className="flex gap-3 rounded-lg px-3 py-2 text-xs hover:bg-slate-50 transition-colors"
                >
                  <span
                    className={`shrink-0 w-10 font-bold ${
                      log.level === "ERROR"
                        ? "text-rose-600"
                        : log.level === "WARN"
                          ? "text-amber-500"
                          : "text-slate-400"
                    }`}
                  >
                    {log.level}
                  </span>
                  <span className="text-slate-600 leading-relaxed">
                    {log.message}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Shared sub-components ── */

function Card({
  title,
  loading,
  error,
  badge,
  children,
}: {
  title: string;
  loading?: boolean;
  error?: string;
  badge?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
          {badge && (
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-500">
              {badge}
            </span>
          )}
        </div>
        {loading && <span className="text-xs text-slate-400">Loading…</span>}
      </div>
      {error ? <p className="text-sm text-rose-600">{error}</p> : children}
    </div>
  );
}

function PerfStat({
  label,
  value,
  loading,
}: {
  label: string;
  value: React.ReactNode;
  loading?: boolean;
}) {
  return (
    <div className="bg-white px-5 py-4">
      <div className="text-xs font-medium text-slate-400 uppercase tracking-wider">
        {label}
      </div>
      <div className="mt-1 text-lg font-bold text-slate-900">
        {loading ? <span className="text-slate-300">—</span> : value}
      </div>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-slate-500">{label}</span>
      <span className="text-sm font-semibold text-slate-800">{value}</span>
    </div>
  );
}
