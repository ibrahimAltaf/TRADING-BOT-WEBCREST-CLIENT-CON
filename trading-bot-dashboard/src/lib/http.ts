import axios, { AxiosError } from "axios";
import { AUTH_TOKEN_KEY } from "../apis/auth/auth.api";

export type ApiError = {
  message: string;
  status?: number;
  data?: unknown;
};

export const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "http://localhost:8000",
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
