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

export function extractError(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const d = err.response?.data?.detail;
    if (typeof d === "string") return d;
    if (d) return JSON.stringify(d, null, 2);
    return err.message;
  }
  return String(err);
}
