import axios, { type AxiosError } from "axios";
import { ElMessage } from "element-plus";
import { getApiBase } from "@/config";
import { getStoredApiKey, getStoredBearer } from "@/api/enterprise";

export const http = axios.create({
  timeout: 300_000,
  headers: { "Content-Type": "application/json" },
});

http.interceptors.request.use((config) => {
  const base = getApiBase();
  config.baseURL = base ? `${base}/api/v1` : "/api/v1";
  const apiKey = getStoredApiKey();
  if (apiKey) config.headers.set("X-API-Key", apiKey);
  const bearer = getStoredBearer();
  if (bearer) config.headers.set("Authorization", `Bearer ${bearer}`);
  return config;
});

http.interceptors.response.use(
  (res) => res,
  (err: AxiosError<{ detail?: string | unknown }>) => {
    const detail = err.response?.data?.detail;
    const msg =
      typeof detail === "string"
        ? detail
        : detail
          ? JSON.stringify(detail)
          : err.message || "请求失败";
    ElMessage.error(msg.slice(0, 500));
    return Promise.reject(err);
  },
);

function formatApiDetail(detail: unknown): string | null {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (item && typeof item === "object" && "msg" in item) {
          const loc = Array.isArray((item as { loc?: unknown }).loc)
            ? (item as { loc: unknown[] }).loc.filter((x) => x !== "body").join(".")
            : "";
          const msg = String((item as { msg?: unknown }).msg ?? "");
          return loc ? `${loc}: ${msg}` : msg;
        }
        return null;
      })
      .filter(Boolean);
    if (parts.length) return parts.join("; ");
  }
  if (detail && typeof detail === "object") return JSON.stringify(detail, null, 2);
  return null;
}

export function extractError(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const d = err.response?.data?.detail;
    const formatted = formatApiDetail(d);
    if (formatted) return formatted;
    return err.message;
  }
  if (err instanceof Error) return err.message;
  return String(err);
}
