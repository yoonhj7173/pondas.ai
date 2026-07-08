// 맵 데이터 타입 — 백엔드 GET /api/projects/{id}/map 응답과 일치.
import type { AgentStatus } from "@/lib/tokens";

export interface AgentNode {
  id: string;
  name: string;
  model_tier: string;
  slot: number;
  status: AgentStatus;
}

export interface TeamRoom {
  id: string;
  name: string;
  template_key: string;
  engine: string;
  room_x: number;
  room_y: number;
  agents: AgentNode[];
  status?: string;          // 팀 카드 pill: idle|working|needs-input|failed|done
  summary?: string | null;  // 최근 활동 1줄 요약(영어)
}

export interface EdgeLink {
  id: string;
  from_agent_id: string;
  to_agent_id: string;
  type: string;
  max_iterations: number | null;
}

export interface MapData {
  project: { id: string; name: string; paused: boolean };
  paused: boolean;
  teams: TeamRoom[];
  edges: EdgeLink[];
}
