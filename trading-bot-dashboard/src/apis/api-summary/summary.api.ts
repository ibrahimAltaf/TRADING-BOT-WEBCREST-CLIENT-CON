import { http } from "../../lib/http";

export type StatusSummaryResponse = {
  app_version: string;
  scheduler_state: string;
  last_decision_time: string | null;
  last_successful_market_fetch: string | null;
  last_successful_trade_execution: string | null;
  model_loaded: boolean;
  database_connected: boolean;
  exchange_connected: boolean;
  exchange_detail: string | null;
};

export type StartupCheckResponse = {
  ok: boolean;
  env: string;
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
