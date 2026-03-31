/**
 * TanStack Query hooks for Exchange API – caching, refetch, dedup.
 */
import {
  useQuery,
  useMutation,
  useQueryClient,
  type UseQueryOptions,
  type UseMutationOptions,
} from "@tanstack/react-query";
import {
  statsApi,
  type LiveProofResponse,
  type MlAnalysisResponse,
} from "../api-summary/summary.api";
import {
  exchangeApi,
  type AutoTradeIn,
  type AutoTradeResponse,
  type ExchangeBalanceResponse,
  type ExchangeDecisionsRecentResponse,
  type ExchangeDecisionLatestResponse,
  type ExchangeLogsRecentResponse,
  type ExchangeProofResponse,
  type ExchangeOpenPositionsResponse,
  type ExchangePositionsHistoryResponse,
  type ExchangeTradesResponse,
  type KlinesResponse,
  type LimitBuyIn,
  type LimitBuyResponse,
  type MlVsRulesResponse,
  type PerformanceMetricsResponse,
  type PerformanceSummaryResponse,
  type TickerPriceResponse,
  type TradeEvaluationResponse,
} from "./exchange.api";

const keys = {
  all: ["exchange"] as const,
  status: () => [...keys.all, "status"] as const,
  healthDb: () => [...keys.all, "healthDb"] as const,
  balances: () => [...keys.all, "balances"] as const,
  balanceAsset: (asset: string) => [...keys.all, "balance", asset] as const,
  positionsOpen: () => [...keys.all, "positionsOpen"] as const,
  positionsHistory: (params?: { symbol?: string }) =>
    [...keys.all, "positionsHistory", params] as const,
  decisionsRecent: (params?: { symbol?: string; limit?: number }) =>
    [...keys.all, "decisionsRecent", params] as const,
  decisionLatest: (symbol: string) =>
    [...keys.all, "decisionLatest", symbol] as const,
  logsRecent: (params?: { limit?: number }) =>
    [...keys.all, "logsRecent", params] as const,
  openOrders: (symbol: string) => [...keys.all, "openOrders", symbol] as const,
  allOrders: (symbol: string, limit?: number) =>
    [...keys.all, "allOrders", symbol, limit] as const,
  trades: (params?: { symbol?: string; limit?: number }) =>
    [...keys.all, "trades", params] as const,
  tickerPrice: (symbol: string) =>
    [...keys.all, "tickerPrice", symbol] as const,
  klines: (symbol: string, interval: string, limit: number) =>
    [...keys.all, "klines", symbol, interval, limit] as const,
  performance: (mode?: string) =>
    [...keys.all, "performance", mode ?? "live"] as const,
  performanceSummary: (mode?: string) =>
    [...keys.all, "performanceSummary", mode ?? "live"] as const,
  mlVsRules: (mode?: string) =>
    [...keys.all, "mlVsRules", mode ?? "live"] as const,
  tradeEvaluation: (mode?: string) =>
    [...keys.all, "tradeEvaluation", mode ?? "live"] as const,
  proof: (symbol?: string) => [...keys.all, "proof", symbol ?? "BTCUSDT"] as const,
};

const statsRoot = ["stats"] as const;
const statsKeys = {
  all: statsRoot,
  liveProof: (limit: number) =>
    [...statsRoot, "liveProof", limit] as const,
  mlAnalysis: (limit: number) =>
    [...statsRoot, "mlAnalysis", limit] as const,
};

export function useStatusQuery(
  options?: UseQueryOptions<
    unknown,
    Error,
    { ok?: boolean; phase?: number; env?: string }
  >,
) {
  return useQuery({
    queryKey: keys.status(),
    queryFn: () =>
      exchangeApi.status() as Promise<{
        ok?: boolean;
        phase?: number;
        env?: string;
      }>,
    refetchInterval: 30_000,
    ...options,
  });
}

export function useHealthDbQuery(
  options?: UseQueryOptions<unknown, Error, { db?: string; select_1?: number }>,
) {
  return useQuery({
    queryKey: keys.healthDb(),
    queryFn: () => exchangeApi.healthDb(),
    refetchInterval: 30_000,
    ...options,
  });
}

export function useBalancesQuery(
  options?: UseQueryOptions<unknown, Error, ExchangeBalanceResponse>,
) {
  return useQuery({
    queryKey: keys.balances(),
    queryFn: () => exchangeApi.balance(),
    refetchInterval: 30_000,
    ...options,
  });
}

export function usePositionsOpenQuery(
  options?: UseQueryOptions<
    unknown,
    Error,
    ExchangeOpenPositionsResponse & { items?: any[]; count?: number }
  >,
) {
  return useQuery({
    queryKey: keys.positionsOpen(),
    queryFn: async () => {
      const data = await exchangeApi.positionsOpen();
      const positions = (data as any)?.positions ?? [];
      return {
        ...data,
        count: (data as any)?.count ?? positions.length,
        positions,
        items: positions,
      };
    },
    refetchInterval: 20_000,
    ...options,
  });
}

export function useDecisionsRecentQuery(
  params: {
    symbol?: string;
    limit?: number;
    action?: "BUY" | "SELL" | "HOLD";
  } = {},
  options?: UseQueryOptions<unknown, Error, ExchangeDecisionsRecentResponse>,
) {
  return useQuery({
    queryKey: keys.decisionsRecent(params),
    queryFn: () => exchangeApi.decisionsRecent(params),
    refetchInterval: 15_000,
    ...options,
  });
}

export function useDecisionLatestQuery(
  symbol: string,
  options?: UseQueryOptions<unknown, Error, ExchangeDecisionLatestResponse>,
) {
  return useQuery({
    queryKey: keys.decisionLatest(symbol),
    queryFn: () => exchangeApi.decisionLatest({ symbol }),
    enabled: !!symbol,
    refetchInterval: 10_000,
    ...options,
  });
}

export function useLogsRecentQuery(
  params: { limit?: number } = {},
  options?: UseQueryOptions<
    unknown,
    Error,
    ExchangeLogsRecentResponse & { items?: any[] }
  >,
) {
  return useQuery({
    queryKey: keys.logsRecent(params),
    queryFn: async () => {
      const data = await exchangeApi.logsRecent(params);
      const items = Array.isArray((data as any)?.logs)
        ? (data as any).logs
        : ((data as any)?.items ?? []);
      return { ...data, logs: items, items };
    },
    refetchInterval: 10_000,
    ...options,
  });
}

export function useOpenOrdersQuery(
  symbol: string,
  options?: UseQueryOptions<unknown, Error, { orders: any[]; count: number }>,
) {
  return useQuery({
    queryKey: keys.openOrders(symbol),
    queryFn: async () => {
      const raw = await exchangeApi.openOrders({ symbol });
      const orders = Array.isArray(raw) ? raw : ((raw as any)?.orders ?? []);
      return { orders, count: orders.length };
    },
    enabled: !!symbol,
    refetchInterval: 15_000,
    ...options,
  });
}

export function useAllOrdersQuery(
  symbol: string,
  limit = 50,
  options?: UseQueryOptions<unknown, Error, { orders: any[]; count: number }>,
) {
  return useQuery({
    queryKey: keys.allOrders(symbol, limit),
    queryFn: async () => {
      const raw = await exchangeApi.allOrders({ symbol, limit });
      const orders = Array.isArray(raw) ? raw : ((raw as any)?.orders ?? []);
      return { orders, count: orders.length };
    },
    enabled: !!symbol,
    refetchInterval: 20_000,
    ...options,
  });
}

export function useTradesQuery(
  params: { symbol?: string; limit?: number } = {},
  options?: UseQueryOptions<unknown, Error, ExchangeTradesResponse>,
) {
  return useQuery({
    queryKey: keys.trades(params),
    queryFn: () => exchangeApi.trades(params),
    refetchInterval: 15_000,
    ...options,
  });
}

export function useProofQuery(
  symbol: string,
  options?: UseQueryOptions<unknown, Error, ExchangeProofResponse>,
) {
  return useQuery({
    queryKey: keys.proof(symbol),
    queryFn: () => exchangeApi.proof({ symbol }),
    enabled: !!symbol,
    refetchInterval: 15_000,
    ...options,
  });
}

export function useTickerPriceQuery(
  symbol: string,
  options?: UseQueryOptions<unknown, Error, TickerPriceResponse>,
) {
  return useQuery({
    queryKey: keys.tickerPrice(symbol),
    queryFn: () => exchangeApi.tickerPrice(symbol),
    enabled: !!symbol,
    refetchInterval: 5_000,
    ...options,
  });
}

export function useKlinesQuery(
  symbol: string,
  interval = "1h",
  limit = 100,
  options?: UseQueryOptions<unknown, Error, KlinesResponse>,
) {
  return useQuery({
    queryKey: keys.klines(symbol, interval, limit),
    queryFn: () => exchangeApi.klines({ symbol, interval, limit }),
    enabled: !!symbol,
    staleTime: 60 * 1000, // 1 min
    ...options,
  });
}

export function usePositionsHistoryQuery(
  params?: { symbol?: string; limit?: number },
  options?: UseQueryOptions<unknown, Error, ExchangePositionsHistoryResponse>,
) {
  return useQuery({
    queryKey: keys.positionsHistory(params),
    queryFn: () => exchangeApi.positionsHistory(params),
    refetchInterval: 30_000,
    ...options,
  });
}

export function usePerformanceQuery(
  mode: "live" | "paper" = "live",
  options?: UseQueryOptions<unknown, Error, PerformanceMetricsResponse>,
) {
  return useQuery({
    queryKey: keys.performance(mode),
    queryFn: () => exchangeApi.performance({ mode }),
    refetchInterval: 30_000,
    ...options,
  });
}

export function usePerformanceSummaryQuery(
  mode: "live" | "paper" = "live",
  options?: UseQueryOptions<unknown, Error, PerformanceSummaryResponse>,
) {
  return useQuery({
    queryKey: keys.performanceSummary(mode),
    queryFn: () => exchangeApi.performanceSummary({ mode }),
    refetchInterval: 30_000,
    ...options,
  });
}

export function useMlVsRulesQuery(
  mode: "live" | "paper" = "live",
  options?: UseQueryOptions<unknown, Error, MlVsRulesResponse>,
) {
  return useQuery({
    queryKey: keys.mlVsRules(mode),
    queryFn: () => exchangeApi.mlVsRules({ mode }),
    refetchInterval: 30_000,
    ...options,
  });
}

export function useTradeEvaluationQuery(
  mode: "live" | "paper" = "live",
  options?: UseQueryOptions<unknown, Error, TradeEvaluationResponse>,
) {
  return useQuery({
    queryKey: keys.tradeEvaluation(mode),
    queryFn: () => exchangeApi.tradeEvaluation({ mode }),
    refetchInterval: 30_000,
    ...options,
  });
}

export function useLiveProofQuery(
  limit = 200,
  options?: UseQueryOptions<unknown, Error, LiveProofResponse>,
) {
  return useQuery({
    queryKey: statsKeys.liveProof(limit),
    queryFn: () => statsApi.liveProof({ limit }),
    refetchInterval: 30_000,
    ...options,
  });
}

export function useMlAnalysisQuery(
  limit = 500,
  options?: UseQueryOptions<unknown, Error, MlAnalysisResponse>,
) {
  return useQuery({
    queryKey: statsKeys.mlAnalysis(limit),
    queryFn: () => statsApi.mlAnalysis({ limit }),
    refetchInterval: 60_000,
    ...options,
  });
}

// Mutations
export function useAutoTradeMutation(
  options?: UseMutationOptions<AutoTradeResponse, Error, AutoTradeIn>,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: AutoTradeIn) => exchangeApi.autoTrade(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.balances() });
      qc.invalidateQueries({ queryKey: keys.positionsOpen() });
      qc.invalidateQueries({ queryKey: keys.decisionsRecent({}) });
    },
    ...options,
  });
}

export function useLimitBuyMutation(
  options?: UseMutationOptions<LimitBuyResponse, Error, LimitBuyIn>,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: LimitBuyIn) => exchangeApi.limitBuy(body),
    onSuccess: (_, variables) => {
      qc.invalidateQueries({ queryKey: keys.balances() });
      qc.invalidateQueries({ queryKey: keys.openOrders(variables.symbol) });
      qc.invalidateQueries({ queryKey: keys.allOrders(variables.symbol) });
    },
    ...options,
  });
}

export function useCancelOrderMutation(
  options?: UseMutationOptions<
    { ok: boolean; cancelled: unknown },
    Error,
    { symbol: string; order_id: number }
  >,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { symbol: string; order_id: number }) =>
      exchangeApi.cancelOrder(body),
    onSuccess: (_, variables) => {
      qc.invalidateQueries({ queryKey: keys.openOrders(variables.symbol) });
      qc.invalidateQueries({ queryKey: keys.allOrders(variables.symbol) });
    },
    ...options,
  });
}
