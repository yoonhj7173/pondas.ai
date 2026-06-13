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
}

interface AgentState {
  status: AgentStatus;
  tokensIn: number;
  tokensOut: number;
}

interface StoreState {
  agents: Record<string, AgentState>;
  agentMeta: Record<string, { name: string; team: string }>;
  events: FeedEvent[];
  unread: number;
  connected: boolean;
  usage: { tokensIn: number; tokensOut: number; cost: number };

  setSnapshot: (data: MapData) => void;
  applyStatus: (agentId: string, status: AgentStatus) => void;
  applyUsage: (agentId: string, tin: number, tout: number, cost: number) => void;
  applyNotification: (agentId: string, type: string, message: string) => void;
  markAllRead: () => void;
  setConnected: (c: boolean) => void;
}

let _eventId = 0;
const FEED_CAP = 200;

export const useStore = create<StoreState>((set) => ({
  agents: {},
  agentMeta: {},
  events: [],
  unread: 0,
  connected: false,
  usage: { tokensIn: 0, tokensOut: 0, cost: 0 },

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
      const ev: FeedEvent = { id: ++_eventId, team: meta.team, agent: meta.name, agentId, status, ts: Date.now() };
      return {
        agents: { ...s.agents, [agentId]: { ...prev, status } },
        events: [ev, ...s.events].slice(0, FEED_CAP),
      };
    }),

  applyUsage: (agentId, tin, tout, cost) =>
    set((s) => {
      const prev = s.agents[agentId] ?? { status: "idle", tokensIn: 0, tokensOut: 0 };
      return {
        agents: { ...s.agents, [agentId]: { ...prev, tokensIn: prev.tokensIn + tin, tokensOut: prev.tokensOut + tout } },
        usage: { tokensIn: s.usage.tokensIn + tin, tokensOut: s.usage.tokensOut + tout, cost: s.usage.cost + cost },
      };
    }),

  applyNotification: (agentId, type, message) =>
    set((s) => ({ unread: s.unread + 1 })),

  markAllRead: () => set({ unread: 0 }),
  setConnected: (c) => set({ connected: c }),
}));
