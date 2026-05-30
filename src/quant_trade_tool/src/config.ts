const STORAGE_KEY = "quant_trade_api_base";

export function getApiBase(): string {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored) return stored.replace(/\/$/, "");
  if (import.meta.env.VITE_API_BASE) return import.meta.env.VITE_API_BASE.replace(/\/$/, "");
  // 与 FastAPI 同端口部署时，API 在同源 /api/v1
  if (import.meta.env.PROD) return window.location.origin;
  return "";
}

export function setApiBase(url: string): void {
  localStorage.setItem(STORAGE_KEY, url.replace(/\/$/, ""));
}

export function docsUrl(): string {
  const base = getApiBase();
  const root = base ? base.replace(/\/api\/v1$/, "") : "http://127.0.0.1:8765";
  return `${root}/docs`;
}
