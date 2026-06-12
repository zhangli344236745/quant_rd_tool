import { ElNotification } from "element-plus";

type NotifyType = "success" | "warning" | "error" | "info";

const ICONS: Record<NotifyType, string> = {
  success: "✓",
  warning: "⚠",
  error: "✕",
  info: "ℹ",
};

function show(type: NotifyType, title: string, message?: string, duration = 4200) {
  ElNotification({
    title: `${ICONS[type]}  ${title}`,
    message,
    type,
    duration,
    position: "top-right",
    customClass: "qrd-notify",
    showClose: true,
  });
}

export function useNotify() {
  return {
    success: (title: string, message?: string) => show("success", title, message),
    warning: (title: string, message?: string) => show("warning", title, message, 5500),
    error: (title: string, message?: string) => show("error", title, message, 6500),
    info: (title: string, message?: string) => show("info", title, message),
  };
}
