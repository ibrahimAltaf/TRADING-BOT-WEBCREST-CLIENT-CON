import { useEffect, useMemo } from "react";
import {
  useStartupCheck,
  useStatusSummary,
} from "../../apis/api-summary/useStatusSummary";

function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

function statusBadge(ok: boolean) {
  return cn(
    "inline-flex rounded-full px-2 py-0.5 text-xs font-semibold",
    ok ? "bg-emerald-50 text-emerald-700" : "bg-rose-50 text-rose-700",
  );
}

function schedulerBadge(state?: string | null) {
  const value = (state ?? "").toLowerCase();

  if (value === "running" || value === "enabled" || value === "active") {
    return "inline-flex rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-semibold text-emerald-700";
  }

  if (value === "paused" || value === "stopped" || value === "disabled") {
    return "inline-flex rounded-full bg-amber-50 px-2 py-0.5 text-xs font-semibold text-amber-700";
  }

  return "inline-flex rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-700";
}

function formatDateTime(value?: string | null) {
  if (!value) return "—";
  const dt = new Date(value);
  return Number.isNaN(dt.getTime()) ? value : dt.toLocaleString();
}

function InfoCard({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        {label}
      </div>
      <div
        className={cn(
          "mt-2 text-sm font-semibold text-slate-900",
          mono && "font-mono text-[13px]",
        )}
      >
        {value}
      </div>
    </div>
  );
}

export default function StatusSummary() {
  const summary = useStatusSummary();
  const startup = useStartupCheck();

  useEffect(() => {
    summary.run();
    startup.run();
  }, []);

  const data = useMemo(() => summary.data, [summary.data]);
  const startupData = useMemo(() => startup.data, [startup.data]);
  const isInitialLoading = summary.loading && !data;

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-sm font-semibold text-slate-900">
              Status Summary
            </div>
            <div className="mt-1 text-xs text-slate-500">
              Live system health, scheduler, model, database, and exchange
              status
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              disabled={summary.loading || startup.loading}
              onClick={() => {
                summary.run();
                startup.run();
              }}
              className="h-9 rounded-lg border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800 disabled:opacity-60"
            >
              {summary.loading || startup.loading ? "Refreshing..." : "Refresh"}
            </button>
          </div>
        </div>

        {summary.error && (
          <div className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
            {summary.error}
          </div>
        )}

        {startup.error && (
          <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
            Startup check: {startup.error}
          </div>
        )}

        {isInitialLoading && (
          <div className="mt-4 flex items-center justify-center px-3 py-10">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-slate-300 border-t-slate-700" />
          </div>
        )}

        {!isInitialLoading && data && (
          <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            <InfoCard
              label="App Version"
              value={startupData?.app_version || data.app_version || "—"}
              mono
            />

            <InfoCard label="Environment" value={startupData?.env || "—"} mono />

            <InfoCard
              label="Scheduler State"
              value={
                <span className={schedulerBadge(data.scheduler_state)}>
                  {data.scheduler_state || "Unknown"}
                </span>
              }
            />

            <InfoCard
              label="Model Loaded"
              value={
                <span
                  className={statusBadge(data.model_loaded)}
                >
                  {data.model_loaded ? "Loaded" : "Not Loaded"}
                </span>
              }
            />

            <InfoCard
              label="Database"
              value={
                <span
                  className={statusBadge(data.database_connected)}
                >
                  {data.database_connected ? "Connected" : "Disconnected"}
                </span>
              }
            />

            <InfoCard
              label="Exchange"
              value={
                <span
                  className={statusBadge(data.exchange_connected)}
                >
                  {data.exchange_connected ? "Connected" : "Disconnected"}
                </span>
              }
            />

            <InfoCard
              label="Exchange Detail"
              value={data.exchange_detail || "—"}
            />

            <InfoCard
              label="Dashboard URL"
              value={startupData?.dashboard_url || "Not configured"}
            />

            <InfoCard
              label="Dashboard Reachability"
              value={
                <span
                  className={statusBadge(Boolean(startupData?.dashboard_connected))}
                >
                  {startupData?.dashboard_connected ? "Reachable" : "Unavailable"}
                </span>
              }
            />

            <InfoCard
              label="Dashboard Detail"
              value={startupData?.dashboard_detail || "—"}
            />

            <InfoCard
              label="Last Decision Time"
              value={formatDateTime(data.last_decision_time)}
            />

            <InfoCard
              label="Last Successful Market Fetch"
              value={formatDateTime(data.last_successful_market_fetch)}
            />

            <InfoCard
              label="Last Successful Trade Execution"
              value={formatDateTime(data.last_successful_trade_execution)}
            />
          </div>
        )}

        {!summary.loading && !summary.error && !data && (
          <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 px-3 py-8 text-center text-sm text-slate-500">
            No status summary available.
          </div>
        )}
      </div>
    </div>
  );
}
