const BJ = "Asia/Shanghai";

/** Format ISO / UTC timestamp as 北京时间 (zh-CN). */
export function formatBeijing(
  iso?: string | null,
  mode: "datetime" | "datetime_min" | "date" | "time" = "datetime",
): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const base: Intl.DateTimeFormatOptions = { timeZone: BJ, hour12: false };
  if (mode === "date") {
    return d.toLocaleDateString("zh-CN", { ...base, year: "numeric", month: "2-digit", day: "2-digit" });
  }
  if (mode === "time") {
    return d.toLocaleTimeString("zh-CN", { ...base, hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }
  if (mode === "datetime_min") {
    return d.toLocaleString("zh-CN", {
      ...base,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  }
  return d.toLocaleString("zh-CN", {
    ...base,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}
