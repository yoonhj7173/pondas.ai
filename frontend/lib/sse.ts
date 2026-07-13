// SSE 연결(item 22) — project:{id} 스트림을 store로 라우팅. 재연결 시 /map+/usage reconcile.
import { useStore } from "@/lib/store";
import { apiFetch } from "@/lib/api";
import type { AgentStatus } from "@/lib/tokens";
import type { MapData } from "@/lib/map/types";

/**
 * connectSSE — 실시간 연결 받는 쪽. 서버가 밀어주는 이벤트를 받아 화면 상태(store)에 반영한다.
 *
 * 무슨 일을 하나: 백엔드의 SSE 스트림(서버가 답을 실시간으로 조각조각 보내는 통로)에 연결해,
 *   "누가 일 시작/완료", "토큰 썼음", "알림" 이벤트가 올 때마다 store의 해당 함수를 호출한다.
 *   → 맵 캐릭터·사용량 바·알림 벨이 새로고침 없이 실시간으로 바뀐다.
 * 누가 부르나: 프로젝트 맵 화면 진입 시 — frontend/app/app/[projectId]/page.tsx.
 * 처리 순서: 1) EventSource로 /sse 연결(토큰은 ?token= 쿼리로 — 브라우저 제약상 헤더 못 씀)
 *   2) 메시지 종류별로 store.applyStatus/applyUsage/applyNotification 호출
 *   3) 끊기면 2초 뒤 재연결하며 /map을 다시 받아 현재 상태를 맞춘다(reconcile — 끊긴 새 누락분 보정).
 * 연결: 이벤트를 보내는 쪽 → backend/app/routers/realtime.py의 sse. 상태 저장소 → store.ts.
 * 반환: 화면을 떠날 때 부르면 연결을 끊는 정리 함수.
 */
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
    // EventSource는 헤더를 못 실어서 ?token= 사용(백엔드 auth가 지원). 토큰이 URL에 노출되는
    // 트레이드오프는 Clerk JWT가 단명(short-lived)이라 영향 제한적; P1에 단기 SSE 전용 토큰 고려.
    es = new EventSource(`${base}/api/projects/${projectId}/sse?token=${encodeURIComponent(token)}`);
    es.onopen = () => useStore.getState().setConnected(true);
    es.onmessage = (e) => {
      let data: any;
      try { data = JSON.parse(e.data); } catch { return; }
      const s = useStore.getState();
      if (data.type === "task_status") s.applyStatus(data.agent_id, data.status as AgentStatus);
      else if (data.type === "progress") s.applyProgress(data.agent_id, data.label ?? ""); // 라이브 진행 한 줄(QA-01)
      else if (data.type === "usage") s.applyUsage(data.agent_id, data.tokens_in ?? 0, data.tokens_out ?? 0, data.cost_usd ?? 0);
      else if (data.type === "notification") s.applyNotification(data.agent_id, data.notif_type, data.message);
      else if (data.type === "paywall") s.triggerPaywall(); // 크레딧 부족 → 결제 모달 자동 노출(D46).
      else if (data.type === "preview_status") s.applyPreview(data.status, data.url ?? null, data.version_no ?? null); // Live Preview 갱신(D49/D51).
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
