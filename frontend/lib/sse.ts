// SSE 연결(item 22) — project:{id} 스트림을 store로 라우팅. 재연결 시 /map+/usage reconcile.
import { useStore } from "@/lib/store";
import { apiFetch } from "@/lib/api";
import type { AgentStatus } from "@/lib/tokens";
import type { MapData } from "@/lib/map/types";

export function connectSSE(projectId: string, token: string): () => void {
  const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  let es: EventSource | null = null;
  let closed = false;
  let retry: ReturnType<typeof setTimeout> | null = null;

  const store = useStore.getState();

  function reconcile() {
    // 재연결 시 권위 스냅샷으로 교체(끊긴 동안의 이벤트 유실돼도 현재 상태는 정확).
    apiFetch<MapData>(`/api/projects/${projectId}/map`, { token })
      .then((d) => useStore.getState().setSnapshot(d))
      .catch(() => {});
  }

  function open() {
    if (closed) return;
    // EventSource는 헤더를 못 실어서 ?token= 사용(백엔드 auth가 지원).
    es = new EventSource(`${base}/api/projects/${projectId}/sse?token=${encodeURIComponent(token)}`);
    es.onopen = () => useStore.getState().setConnected(true);
    es.onmessage = (e) => {
      let data: any;
      try { data = JSON.parse(e.data); } catch { return; }
      const s = useStore.getState();
      if (data.type === "task_status") s.applyStatus(data.agent_id, data.status as AgentStatus);
      else if (data.type === "usage") s.applyUsage(data.agent_id, data.tokens_in ?? 0, data.tokens_out ?? 0, data.cost_usd ?? 0);
      else if (data.type === "notification") s.applyNotification(data.agent_id, data.notif_type, data.message);
    };
    es.onerror = () => {
      useStore.getState().setConnected(false);
      es?.close();
      if (!closed) {
        if (retry) clearTimeout(retry);
        retry = setTimeout(() => { reconcile(); open(); }, 2000);
      }
    };
  }

  open();
  return () => {
    closed = true;
    if (retry) clearTimeout(retry);
    es?.close();
    store.setConnected(false);
  };
}
