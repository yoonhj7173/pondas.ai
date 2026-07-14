// 단일 클라이언트 상태 store(item 22) — 모든 비주얼이 여기서 파생된다(D36).
// agents = 스냅샷(last-write-wins, glow/badge/chip), events = append-only 링(피드/토스트/벨).
// 권위는 서버; 이건 그 투영이다. 같은 SSE가 둘 다 갱신해 불일치가 구조적으로 불가능.
import { create } from "zustand";
import type { AgentStatus } from "@/lib/tokens";
import type { MapData } from "@/lib/map/types";

export interface FeedEvent {
  id: number;
  team: string;
  agent: string;
  agentId: string;
  status: string;
  ts: number;
  kind?: "status" | "chat"; // chat = 오케스트레이터 답변 도착(채팅 닫힘 중 알림, QA-06)
  detail?: string;          // 부가 한 줄(채팅 미리보기 등)
}

// 영속 알림(QA-04 통합 Activity) — DB notifications의 투영. 종결 이벤트(done/failed/needs-input)의
// 뼈대: 새로고침해도 남고 읽음 상태가 있다. 휘발 이벤트(working/chat)는 위 FeedEvent가 담당.
export interface NotifRow {
  id: string;
  agentId: string | null;
  type: string;      // done | failed | needs-input | blocked
  message: string;
  read: boolean;
  ts: number;
}

interface AgentState {
  status: AgentStatus;
  tokensIn: number;
  tokensOut: number;
}

// Live Preview 상태(Phase 2, D49) — 시어터가 여기서 iframe/버전칩을 파생.
export interface PreviewState {
  status: string; // none|disabled|starting|ready|error|paused
  url: string | null;
  versionNo: number | null;
}

interface StoreState {
  agents: Record<string, AgentState>;
  agentMeta: Record<string, { name: string; team: string }>;
  events: FeedEvent[];
  unread: number;
  connected: boolean;
  usage: { tokensIn: number; tokensOut: number; cost: number };
  paywall: boolean; // 크레딧 부족으로 task가 막힘 → 결제 모달 자동 노출 신호(D46).
  preview: PreviewState; // Live Preview 상태(D49)
  theaterOpen: boolean;  // 시어터 오버레이 열림(D51)
  // 에이전트별 라이브 진행 한 줄(QA-01) — "Writing src/App.tsx" 등. SSE progress 이벤트의 투영.
  progress: Record<string, { label: string; ts: number }>;
  notifs: NotifRow[]; // 영속 알림(QA-04) — 통합 Activity 타임라인의 뼈대
  // 에이전트별 서브태스크 체크리스트(QA-06) — SSE plan 이벤트의 투영. [{title, done}]
  plans: Record<string, { title: string; done: boolean }[]>;
  // 채팅창 라이브 이벤트 라인(B1) — 태스크 종결을 채팅에도 회색 한 줄로. LLM 없는 canned 브리핑.
  chatEvents: { id: number; text: string }[];

  setSnapshot: (data: MapData) => void;
  applyStatus: (agentId: string, status: AgentStatus) => void;
  applyUsage: (agentId: string, tin: number, tout: number, cost: number) => void;
  applyNotification: (agentId: string, type: string, message: string, notifId?: string) => void;
  applyProgress: (agentId: string, label: string) => void;
  applyPlan: (agentId: string, steps: { title: string; done: boolean }[]) => void;
  pushChatEvent: (preview: string) => void; // 채팅 닫힘 중 오케 답변 도착 → 피드+벨(QA-06)
  applyChatEvent: (text: string) => void; // 태스크 종결 → 채팅 이벤트 라인 append(B1)
  setNotifications: (rows: NotifRow[]) => void; // GET /notifications 결과 반영(마운트 시)
  triggerPaywall: () => void;
  clearPaywall: () => void;
  applyPreview: (status: string, url: string | null, versionNo: number | null) => void;
  setTheater: (open: boolean) => void;
  markAllRead: () => void;
  setConnected: (c: boolean) => void;
}

let _eventId = 0;
const FEED_CAP = 200;

/**
 * useStore — 화면 전체가 공유하는 단일 상태 보관소(Zustand). 모든 비주얼이 여기서 나온다.
 *
 * 무슨 일을 하나: 에이전트별 상태/토큰, 이벤트 피드, 안 읽은 알림 수, 연결 여부, 총 사용량을 한곳에 담는다.
 *   '권위'(진짜 정보)는 서버 DB이고, 이건 그것의 실시간 투영일 뿐이다. 같은 SSE 이벤트가 화면 곳곳을
 *   동시에 갱신하므로 부분별로 어긋날 일이 구조적으로 없다.
 * 누가 쓰나: 맵·HUD·패널 컴포넌트가 useStore(...)로 필요한 조각만 구독한다. SSE가 아래 액션들을 호출해 갱신.
 * 주요 액션: setSnapshot(/map 전체 교체), applyStatus(상태 1건 갱신+피드 추가), applyUsage(토큰/비용 누적).
 * 연결: 이 값을 채우는 쪽 → frontend/lib/sse.ts. 색/표정 변환 → frontend/lib/tokens.ts.
 *   (Spring 비유: 서버가 Entity 원본, 이 store는 화면용 캐시 DTO 모음)
 */
export const useStore = create<StoreState>((set) => ({
  agents: {},
  agentMeta: {},
  events: [],
  unread: 0,
  connected: false,
  usage: { tokensIn: 0, tokensOut: 0, cost: 0 },
  paywall: false,
  preview: { status: "none", url: null, versionNo: null },
  theaterOpen: false,
  progress: {},
  notifs: [],
  plans: {},
  chatEvents: [],

  // /map 스냅샷으로 교체(초기 + 재연결 reconcile).
  setSnapshot: (data) =>
    set(() => {
      const agents: Record<string, AgentState> = {};
      const meta: Record<string, { name: string; team: string }> = {};
      for (const team of data.teams) {
        for (const a of team.agents) {
          agents[a.id] = { status: a.status, tokensIn: 0, tokensOut: 0 };
          meta[a.id] = { name: a.name, team: team.name };
        }
      }
      return { agents, agentMeta: meta };
    }),

  applyStatus: (agentId, status) =>
    set((s) => {
      const prev = s.agents[agentId] ?? { status: "idle", tokensIn: 0, tokensOut: 0 };
      const meta = s.agentMeta[agentId] ?? { name: "Agent", team: "" };
      const ev: FeedEvent = { id: ++_eventId, team: meta.team, agent: meta.name, agentId, status, ts: Date.now(), kind: "status" };
      // 종결 상태로 바뀌면 진행 한 줄/plan은 낡은 정보 → 지운다(QA-01/06).
      const active = ["working", "queued"].includes(status);
      const progress = active
        ? s.progress
        : (() => { const p = { ...s.progress }; delete p[agentId]; return p; })();
      const plans = active
        ? s.plans
        : (() => { const p = { ...s.plans }; delete p[agentId]; return p; })();
      return {
        agents: { ...s.agents, [agentId]: { ...prev, status } },
        events: [ev, ...s.events].slice(0, FEED_CAP),
        progress,
        plans,
      };
    }),

  // 라이브 진행(QA-01) — 러너의 "지금 뭐 하는 중" 한 줄. 피드 행이 아니라 최신값 교체(플러딩 방지).
  applyProgress: (agentId, label) =>
    set((s) => ({ progress: { ...s.progress, [agentId]: { label, ts: Date.now() } } })),

  // 서브태스크 체크리스트(QA-06) — update_plan 도구의 투영. 최신값 교체.
  applyPlan: (agentId, steps) =>
    set((s) => ({ plans: { ...s.plans, [agentId]: steps } })),

  // 채팅 닫힘 중 오케스트레이터 답변 도착 → 피드 행 + 벨 뱃지(QA-06).
  pushChatEvent: (preview) =>
    set((s) => {
      const ev: FeedEvent = {
        id: ++_eventId, team: "", agent: "Orchestrator", agentId: "", status: "replied",
        ts: Date.now(), kind: "chat", detail: preview.length > 120 ? preview.slice(0, 117) + "…" : preview,
      };
      return { events: [ev, ...s.events].slice(0, FEED_CAP), unread: s.unread + 1 };
    }),

  // 태스크 종결 이벤트 → 채팅 라인(B1). 열려 있으면 즉시 보이고, 닫혀 있으면 다음 오픈 때
  // 히스토리(role=event 행)로도 어차피 온다 — 여기는 라이브 표시만 담당.
  applyChatEvent: (text) =>
    set((s) => ({ chatEvents: [...s.chatEvents, { id: ++_eventId, text }].slice(-50) })),

  applyUsage: (agentId, tin, tout, cost) =>
    set((s) => {
      const prev = s.agents[agentId] ?? { status: "idle", tokensIn: 0, tokensOut: 0 };
      return {
        agents: { ...s.agents, [agentId]: { ...prev, tokensIn: prev.tokensIn + tin, tokensOut: prev.tokensOut + tout } },
        usage: { tokensIn: s.usage.tokensIn + tin, tokensOut: s.usage.tokensOut + tout, cost: s.usage.cost + cost },
      };
    }),

  // SSE notification → 영속 알림 행을 실시간 prepend(QA-04) + 벨 뱃지 +1.
  applyNotification: (agentId, type, message, notifId) =>
    set((s) => ({
      unread: s.unread + 1,
      notifs: [
        { id: notifId ?? `local_${++_eventId}`, agentId: agentId || null, type, message, read: false, ts: Date.now() },
        ...s.notifs,
      ].slice(0, 100),
    })),

  // 로드 시 미읽음 수도 서버 기준으로 복원 — 헤더 뱃지/읽음 버튼이 영속 미읽음을 반영(QA-04).
  setNotifications: (rows) =>
    set(() => ({ notifs: rows.slice(0, 100), unread: rows.filter((r) => !r.read).length })),

  triggerPaywall: () => set({ paywall: true }),
  clearPaywall: () => set({ paywall: false }),

  // 프리뷰 상태 갱신(SSE preview_status / start·sync 응답). 과도기 상태는 직전 url/버전 유지.
  applyPreview: (status, url, versionNo) =>
    set((s) => ({
      preview: {
        status,
        url: url ?? (status === "ready" ? s.preview.url : status === "paused" || status === "none" ? null : s.preview.url),
        versionNo: versionNo ?? s.preview.versionNo,
      },
    })),
  setTheater: (open) => set({ theaterOpen: open }),
  // 로컬 읽음 처리 — 서버 read-all POST는 호출부(Hud)가 담당(QA-04).
  markAllRead: () => set((s) => ({ unread: 0, notifs: s.notifs.map((n) => ({ ...n, read: true })) })),
  setConnected: (c) => set({ connected: c }),
}));
