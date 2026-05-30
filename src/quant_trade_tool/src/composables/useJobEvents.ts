import { onUnmounted, ref } from "vue";
import { getApiBase } from "@/config";
import { getStoredApiKey, getStoredBearer } from "@/api/enterprise";

export function useJobEvents(jobId: () => string | undefined) {
  const logs = ref<{ level?: string; message?: string; progress?: number; created_at?: string }[]>(
    [],
  );
  const terminal = ref(false);
  let es: EventSource | null = null;

  function connect() {
    const id = jobId();
    if (!id) return;
    disconnect();
    const base = getApiBase();
    const prefix = base ? base.replace(/\/$/, "") : `${window.location.origin}/api/v1`;
    const url = new URL(`${prefix}/jobs/${id}/events`);
    const key = getStoredApiKey();
    const token = getStoredBearer();
    if (key) url.searchParams.set("api_key", key);
    if (token) url.searchParams.set("token", token);
    es = new EventSource(url.toString());
    es.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        if (data.type === "terminal") {
          terminal.value = true;
          disconnect();
          return;
        }
        logs.value.push(data);
      } catch {
        /* ignore */
      }
    };
    es.onerror = () => disconnect();
  }

  function disconnect() {
    if (es) {
      es.close();
      es = null;
    }
  }

  onUnmounted(disconnect);

  return { logs, terminal, connect, disconnect };
}
