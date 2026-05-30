import { http } from "./http";

export interface NetworkSettings {
  http_proxy: string;
  https_proxy: string;
  no_proxy: string;
}

export const settingsApi = {
  getNetwork: () => http.get<NetworkSettings>("/settings/network"),
  saveNetwork: (body: NetworkSettings) => http.post<NetworkSettings>("/settings/network", body),
  exportBundle: () =>
    http.get<{ settings: Record<string, unknown>; watchlist: { code: string; name: string }[] }>(
      "/settings/export",
    ),
  importBundle: (body: { settings?: Record<string, unknown>; watchlist?: { code: string; name: string }[] }) =>
    http.post<{ status: string }>("/settings/import", body),
};
