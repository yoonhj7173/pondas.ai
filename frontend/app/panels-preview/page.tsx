"use client";

// 패널/모달 비주얼 프리뷰(개발용).
import { useState } from "react";
import { AgentPanel, TeamPanel } from "@/components/panels/InspectorPanel";
import { AddAgentModal, AddTeamModal } from "@/components/panels/Modals";
import type { AgentPanelData, RoleTemplate, TeamPanelData, TeamTemplate } from "@/components/panels/types";

const TEAM: TeamPanelData = {
  id: "t1", name: "Development", template_key: "development", engine: "agent_sdk", agent_count: 3, tokens_total: 18420,
  agents: [
    { id: "a1", name: "SWE", model_tier: "strong", slot: 0, status: "working" },
    { id: "a2", name: "QA", model_tier: "medium", slot: 1, status: "needs-input" },
    { id: "a3", name: "Architect", model_tier: "strong", slot: 2, status: "idle" },
  ],
};
const AGENT: AgentPanelData = {
  id: "a2", team_id: "t1", name: "QA", role_instructions: "You are a QA engineer. Verify real behavior by running the app.", model_tier: "medium",
  status: "needs-input", tokens_total: 9120,
  current_task_id: "task-1", awaiting_prompt: "Which database should I assume — Postgres or SQLite?", error_summary: null,
  last_result_markdown: "### Cafe Finder v1 완성 ☕\n랜딩 + 카페 리스트를 구현하고 샌드박스에서 렌더링 확인까지 마쳤어요.\n\n- 랜딩: 히어로 + 검색바 + 인기 카페 3곳\n- 리스트: 평점순 정렬, 모바일 반응형\n\n```tsx\nexport default function Page() { return <CafeList /> }\n```",
  last_task_id: "task-0", last_output_count: 7,
  outgoing: { id: "e1", to_agent_id: "a1", to_agent_name: "SWE", type: "review_loop", max_iterations: 5 }, incoming: [],
};
const ROLES: RoleTemplate[] = [
  { role_key: "swe", display_name: "Software Engineer", default_tier: "strong", is_starter: true, default_output_type: null, default_output_target_role_key: null, default_max_iterations: null },
  { role_key: "qa", display_name: "QA Engineer", default_tier: "medium", is_starter: false, default_output_type: "review_loop", default_output_target_role_key: "swe", default_max_iterations: 5 },
  { role_key: "architect", display_name: "Architect", default_tier: "strong", is_starter: false, default_output_type: "handoff", default_output_target_role_key: "swe", default_max_iterations: null },
  { role_key: "devops", display_name: "DevOps", default_tier: "medium", is_starter: false, default_output_type: null, default_output_target_role_key: null, default_max_iterations: null },
];
const TEMPLATES: TeamTemplate[] = [
  { key: "planning", name: "Product Planning", description: "PRDs and specs.", engine: "crew", roles: [] },
  { key: "research", name: "Research", description: "Markets, competitors, users.", engine: "crew", roles: [] },
  { key: "design", name: "Design", description: "UI code + screenshots.", engine: "agent_sdk", roles: [] },
  { key: "development", name: "Development", description: "Build + verify software.", engine: "agent_sdk", roles: [] },
];

export default function PanelsPreview() {
  const [view, setView] = useState<"team" | "agent" | "addAgent" | "addTeam">("agent");
  return (
    <div className="relative h-screen w-screen" style={{ background: "#C6C9BC" }}>
      <div className="absolute left-1/2 top-4 z-50 flex -translate-x-1/2 gap-1 rounded-tile bg-white/80 p-2">
        {(["team", "agent", "addAgent", "addTeam"] as const).map((v) => (
          <button key={v} onClick={() => setView(v)} className="rounded-pill border-2 border-white bg-primary-to px-3 py-1 text-xs font-bold text-white">{v}</button>
        ))}
      </div>
      {view === "team" && <TeamPanel data={TEAM} onClose={() => {}} onAddAgent={() => {}} onSelectAgent={() => {}} onRemove={() => {}} />}
      {view === "agent" && <AgentPanel data={AGENT} onClose={() => {}} onStop={() => {}} onRemove={() => {}} onProvideInput={() => {}} />}
      {view === "addAgent" && <AddAgentModal roles={ROLES} teamAgents={TEAM.agents} full={false} onClose={() => {}} onSubmit={() => {}} />}
      {view === "addTeam" && <AddTeamModal templates={TEMPLATES} inOffice={new Set(["development"])} onClose={() => {}} onSubmit={() => {}} />}
    </div>
  );
}
