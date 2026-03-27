import { http } from "../../lib/http";

export type StatusSummaryResponse = {
  app_version: string;
  env?: string;
  binance_testnet?: boolean;
  binance_spot_base_url?: string;
  scheduler_state: string;
  last_decision_time: string | null;
  latest_decision?: {
    action: string;
    confidence: number | null;
    reason: string;
    symbol: string;
    timeframe: string;
    executed: boolean;
    order_id: number | null;
  } | null;
  last_successful_market_fetch: string | null;
  last_successful_trade_execution: string | null;
  model_loaded: boolean;
  database_connected: boolean;
  exchange_connected: boolean;
  exchange_detail: string | null;
  observability?: {
    recent_decisions_count: number;
    recent_trades_count: number;
  };
};

export type StartupCheckResponse = {
  ok: boolean;
  env: string;
  binance_testnet?: boolean;
  binance_spot_base_url?: string;
  app_version: string;
  scheduler_state: string;
  database_connected: boolean;
  exchange_connected: boolean;
  dashboard_url: string | null;
  dashboard_connected: boolean;
  dashboard_detail: string | null;
  last_decision_time: string | null;
  last_successful_market_fetch: string | null;
  last_successful_trade_execution: string | null;
  latest_decision?: StatusSummaryResponse["latest_decision"];
  observability?: StatusSummaryResponse["observability"];
};

export const statusApi = {
  summary: async (signal?: AbortSignal) => {
    try {
      const r = await http.get<StatusSummaryResponse>("/status/summary", {
        signal,
      });
      return r.data;
    } catch {
      const r = await http.get<StatusSummaryResponse>("/status-summary", {
        signal,
      });
      return r.data;
    }
  },
  startupCheck: async (signal?: AbortSignal) => {
    const r = await http.get<StartupCheckResponse>("/status/startup-check", {
      signal,
    });
    return r.data;
  },
};
