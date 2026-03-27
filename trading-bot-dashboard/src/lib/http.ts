import axios, { AxiosError } from "axios";
import { AUTH_TOKEN_KEY } from "../apis/auth/auth.api";

export type ApiError = {
  message: string;
  status?: number;
  data?: unknown;
};

// Live VPS API via nginx (:80 /api → backend). Never call :8000 from the browser.
const DEFAULT_API_BASE = "http://147.93.96.42/api";

/** Old builds baked `http://host:8000` — rewrite to same host `/api` so nginx proxy works. */
function normalizeApiBase(raw: string): string {
  const s = raw.trim() || DEFAULT_API_BASE;
  if (!s.includes(":8000")) return s;
  const withoutPort = s.replace(/:8000\/?$/, "").replace(/\/$/, "");
  return `${withoutPort}/api`;
}

const API_BASE = normalizeApiBase(
  String(import.meta.env.VITE_API_BASE_URL || "").trim() || DEFAULT_API_BASE,
);

export const http = axios.create({
  baseURL: API_BASE,
  timeout: 30_000,
  headers: { "Content-Type": "application/json" },
});

http.interceptors.request.use((config) => {
  const token = localStorage.getItem(AUTH_TOKEN_KEY);
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

export function toApiError(err: unknown): ApiError {
  if (axios.isAxiosError(err)) {
    const e = err as AxiosError<any>;
    const status = e.response?.status;
    const data = e.response?.data;

    let message = e.message || "Request failed";

    if (typeof data === "string") message = data;
    else if (typeof data?.detail === "string") message = data.detail;
    else if (Array.isArray(data?.detail)) {
      message =
        data.detail
          .map((x: any) => x?.msg)
          .filter(Boolean)
          .join("\n") || message;
    } else if (typeof data?.message === "string") message = data.message;

    return { message, status, data };
  }

  return { message: (err as any)?.message || "Unknown error" };
}
