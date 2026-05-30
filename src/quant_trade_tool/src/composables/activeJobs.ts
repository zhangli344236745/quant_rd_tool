import { computed, onUnmounted, ref } from "vue";
import { jobsApi, type JobRecord } from "@/api/jobs";

const items = ref<JobRecord[]>([]);
let subscribers = 0;
let timer: ReturnType<typeof setInterval> | undefined;
let inflight: Promise<void> | null = null;

async function refreshJobs() {
  if (inflight) return inflight;
  inflight = (async () => {
    try {
      const { data } = await jobsApi.list({ limit: 50 });
      items.value = data.items;
    } catch {
      /* ignore poll errors */
    } finally {
      inflight = null;
    }
  })();
  return inflight;
}

function startPolling() {
  if (timer) return;
  void refreshJobs();
  timer = setInterval(() => void refreshJobs(), 3000);
}

function stopPolling() {
  if (timer) {
    clearInterval(timer);
    timer = undefined;
  }
}

/** Shared job list poll — one interval for badge + drawer. */
export function useActiveJobsPoll() {
  subscribers += 1;
  startPolling();
  onUnmounted(() => {
    subscribers -= 1;
    if (subscribers <= 0) stopPolling();
  });
  const activeCount = computed(
    () => items.value.filter((j) => j.status === "queued" || j.status === "running").length,
  );
  return { items, activeCount, refresh: refreshJobs };
}
