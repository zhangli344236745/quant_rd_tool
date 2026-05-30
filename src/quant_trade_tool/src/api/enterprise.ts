import { http } from "./http";

const API_KEY_STORAGE = "quant_rd_api_key";
const BEARER_STORAGE = "quant_rd_bearer_token";

export function getStoredApiKey(): string {
  return localStorage.getItem(API_KEY_STORAGE) || "";
}

export function setStoredApiKey(key: string) {
  if (key) localStorage.setItem(API_KEY_STORAGE, key);
  else localStorage.removeItem(API_KEY_STORAGE);
}

export function getStoredBearer(): string {
  return localStorage.getItem(BEARER_STORAGE) || "";
}

export function setStoredBearer(token: string) {
  if (token) localStorage.setItem(BEARER_STORAGE, token);
  else localStorage.removeItem(BEARER_STORAGE);
}

export const enterpriseApi = {
  status: () =>
    http.get<{
      enabled: boolean;
      require_auth: boolean;
      audit_enabled: boolean;
      api_key_count: number;
      login_available: boolean;
    }>("/enterprise/status"),

  login: (password: string) =>
    http.post<{ token: string; expires_in: number }>("/enterprise/login", { password }),

  audit: (params?: { limit?: number }) =>
    http.get<{ count: number; items: Record<string, unknown>[] }>("/enterprise/audit", { params }),

  saveSettings: (body: {
    enabled?: boolean;
    require_auth?: boolean;
    audit_enabled?: boolean;
    api_keys?: { id: string; label: string; key: string }[];
  }) => http.post("/enterprise/settings", body),
};
