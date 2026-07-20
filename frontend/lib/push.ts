// Web Push 구독(item 39, D56⑤) — SW 등록 → 권한 → 구독 → 백엔드 저장.
// iOS Safari는 홈스크린 설치 후에만 동작(온보딩 카피에서 안내).
import { apiFetch } from "@/lib/api";

function b64ToUint8(base64: string): Uint8Array {
  const pad = "=".repeat((4 - (base64.length % 4)) % 4);
  const raw = atob((base64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

export function pushSupported(): boolean {
  return typeof window !== "undefined" && "serviceWorker" in navigator && "PushManager" in window;
}

/** 서버 설정 확인 → 권한 요청 → 구독 → 저장. 성공 시 true. */
export async function enablePush(token: string | null): Promise<boolean> {
  if (!pushSupported()) return false;
  const cfg = await apiFetch<{ enabled: boolean; vapid_public_key: string | null }>(
    "/api/push/config", { token });
  if (!cfg.enabled || !cfg.vapid_public_key) return false;
  const reg = await navigator.serviceWorker.register("/sw.js");
  const perm = await Notification.requestPermission();
  if (perm !== "granted") return false;
  const sub = await reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: b64ToUint8(cfg.vapid_public_key) as BufferSource,
  });
  const json = sub.toJSON();
  await apiFetch("/api/push/subscribe", {
    method: "POST", token,
    body: JSON.stringify({ endpoint: json.endpoint, keys: json.keys ?? {} }),
  });
  return true;
}

export function pushGranted(): boolean {
  return pushSupported() && Notification.permission === "granted";
}
