// 패널/모달 페이로드 타입 — 백엔드 schemas와 일치.
import type { AgentStatus } from "@/lib/tokens";

export interface AgentRow { id: string; name: string; model_tier: string; slot: number; status: AgentStatus }

export interface TeamPanelData {
  id: string; name: string; template_key: string; engine: string;
  agent_count: number; tokens_total: number; agents: AgentRow[];
}

export interface EdgeRef { id: string; to_agent_id: string; to_agent_name: string; type: string; max_iterations: number | null }

export interface AgentPanelData {
  id: string; team_id: string; name: string; role_instructions: string; model_tier: string;
  status: AgentStatus; tokens_total: number;
  current_task_id: string | null; awaiting_prompt: string | null; error_summary: string | null;
  active_started_at: string | null; // 진행 중 경과시간 표시용
  failed_task_id: string | null; // 실패한 최신 task → Retry 대상
  // 최근 결과 인-플로우(Phase 2, D51)
  last_result_markdown: string | null; last_task_id: string | null; last_output_count: number;
  outgoing: EdgeRef | null; incoming: EdgeRef[];
}

export interface RoleTemplate {
  role_key: string; display_name: string; role_instructions: string; default_tier: string; is_starter: boolean;
  default_output_type: string | null; default_output_target_role_key: string | null; default_max_iterations: number | null;
}
export interface TeamTemplate { key: string; name: string; description: string; engine: string; roles: RoleTemplate[] }
