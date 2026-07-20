"use client";

// 패널/모달 컨트롤러(item 24) — 맵/HUD 선택을 받아 데이터 fetch + 패널/모달 렌더 + 제출.
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { MapData } from "@/lib/map/types";
import { AgentPanel, TeamPanel } from "./InspectorPanel";
import { AddAgentModal, AddTeamModal, ConfirmDialog, type AgentSubmit } from "./Modals";
import type { AgentPanelData, TeamPanelData, TeamTemplate } from "./types";

export type Selection =
  | { kind: "none" }
  | { kind: "team"; id: string }
  | { kind: "agent"; id: string }
  | { kind: "addAgent"; teamId: string }
  | { kind: "addTeam" };

/**
 * PanelController — 맵에서 무엇을 선택했는지(sel)에 따라 알맞은 패널·모달을 띄우고 동작을 처리한다.
 *
 * 무슨 일을 하나: 선택 상태(sel: 팀/에이전트/팀추가/에이전트추가)에 맞춰 ① 필요한 데이터를 백엔드에서
 *   불러오고 ② 해당 패널(InspectorPanel) 또는 모달(Modals)을 렌더하고 ③ 거기서 일어난 동작(추가·삭제·
 *   Stop·입력제공)을 call()로 백엔드에 보낸 뒤 onChanged로 맵을 새로고침한다. 에러는 상단 배너로 띄운다.
 * 누가 부르나: 메인 맵 화면 — frontend/app/app/[projectId]/page.tsx.
 * 연결: 데이터/동작 호출 → frontend/lib/api.ts(→ teams.py/tasks.py/edges.py). 화면 조각 → InspectorPanel.tsx, Modals.tsx.
 */
export function PanelController({ projectId, getToken, mapData, sel, setSel, onChanged, onOpenOutputs, onOpenTheater }: {
  projectId: string; getToken: () => Promise<string | null>; mapData: MapData;
  sel: Selection; setSel: (s: Selection) => void; onChanged: () => void; onOpenOutputs?: () => void; onOpenTheater?: () => void;
}) {
  const [team, setTeam] = useState<TeamPanelData | null>(null);
  const [agent, setAgent] = useState<AgentPanelData | null>(null);
  const [templates, setTemplates] = useState<TeamTemplate[]>([]);
  const [confirm, setConfirm] = useState<null | { title: string; body: string; run: () => void }>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false); // 액션 진행 중 — 더블클릭(이중 디스패치/이중과금) 차단.

  // 진행 중이면 무시하고, 끝날 때까지 busy를 잡아 버튼을 비활성화한다. call()이 이미 에러를 표면화.
  async function guard(fn: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    try { await fn(); } catch { /* call()이 err 배너로 이미 표시 */ } finally { setBusy(false); }
  }

  useEffect(() => {
    (async () => {
      const token = await getToken();
      if (sel.kind === "team") setTeam(await apiFetch(`/api/teams/${sel.id}`, { token }));
      else if (sel.kind === "agent") setAgent(await apiFetch(`/api/agents/${sel.id}`, { token }));
      else if (sel.kind === "addTeam" || sel.kind === "addAgent") setTemplates(await apiFetch(`/api/templates`, { token }));
    })().catch(() => {});
  }, [sel, getToken]);

  async function call(path: string, method: string, body?: object) {
    try {
      const token = await getToken();
      await apiFetch(path, { method, token, body: body ? JSON.stringify(body) : undefined });
      onChanged();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Action failed");
      setTimeout(() => setErr(null), 4000);
      throw e;
    }
  }

  const errBanner = err ? (
    <div className="fixed left-1/2 top-20 z-[70] -translate-x-1/2 rounded-pill border-[2.5px] border-white bg-status-failed px-4 py-2 text-sm font-bold text-white shadow-card">{err}</div>
  ) : null;

  const close = () => setSel({ kind: "none" });

  if (sel.kind === "team" && team) {
    return (
      <>
        <TeamPanel data={team} onClose={close}
          onAddAgent={() => setSel({ kind: "addAgent", teamId: team.id })}
          onSelectAgent={(id) => setSel({ kind: "agent", id })}
          onRemove={() => setConfirm({ title: "Remove team?", body: `${team.name} and its agents/edges will be removed.`, run: async () => { await call(`/api/teams/${team.id}`, "DELETE"); close(); } })} />
        {confirmEl()}
        {errBanner}
      </>
    );
  }
  if (sel.kind === "agent" && agent) {
    // 프리뷰 카드 노출 조건: agent_sdk 팀(개발/디자인) + 결과물 존재(D51). 실제 runnable 여부는 시어터가 판정.
    const agentTeam = mapData.teams.find((t) => t.agents.some((a) => a.id === agent.id));
    const canPreview = agentTeam?.engine === "agent_sdk" && (agent.last_output_count ?? 0) > 0;
    return (
      <>
        <AgentPanel data={agent} onClose={close} onViewOutputs={onOpenOutputs} busy={busy}
          canPreview={canPreview} onOpenTheater={onOpenTheater}
          onStop={() => guard(async () => { if (agent.current_task_id) { await call(`/api/tasks/${agent.current_task_id}/stop`, "POST"); setSel({ kind: "agent", id: agent.id }); } })}
          onProvideInput={(text) => guard(async () => { if (agent.current_task_id) { await call(`/api/tasks/${agent.current_task_id}/continue`, "POST", { input: text }); setSel({ kind: "agent", id: agent.id }); } })}
          onRetry={() => guard(async () => { if (agent.failed_task_id) { await call(`/api/tasks/${agent.failed_task_id}/retry`, "POST"); setSel({ kind: "agent", id: agent.id }); } })}
          onFix={() => guard(async () => { if (agent.failed_task_id) { await call(`/api/tasks/${agent.failed_task_id}/fix`, "POST"); setSel({ kind: "agent", id: agent.id }); } })}
          onRemove={() => setConfirm({ title: "Remove agent?", body: `${agent.name} will be removed.`, run: async () => { await call(`/api/agents/${agent.id}`, "DELETE"); close(); } })} />
        {confirmEl()}
        {errBanner}
      </>
    );
  }
  if (sel.kind === "addAgent") {
    const teamRoom = mapData.teams.find((t) => t.id === sel.teamId);
    const roles = templates.find((t) => t.key === teamRoom?.template_key)?.roles ?? [];
    const full = (teamRoom?.agents.length ?? 0) >= 5;
    return (
      <>
        <AddAgentModal roles={roles} teamAgents={(teamRoom?.agents ?? []).map((a) => ({ ...a }))} full={full} onClose={close}
          onSubmit={async (a: AgentSubmit) => { try { await call(`/api/teams/${sel.teamId}/agents`, "POST", a); close(); } catch { /* banner */ } }} />
        {errBanner}
      </>
    );
  }
  if (sel.kind === "addTeam") {
    const inOffice = new Set(mapData.teams.map((t) => t.template_key));
    return (
      <>
        <AddTeamModal templates={templates} inOffice={inOffice} onClose={close}
          onSubmit={async (keys) => { try { for (const key of keys) await call(`/api/projects/${projectId}/teams`, "POST", { template_key: key }); close(); } catch { /* banner; partial creation stays, modal open for retry */ } }} />
        {errBanner}
      </>
    );
  }
  return null;

  function confirmEl() {
    if (!confirm) return null;
    return <ConfirmDialog title={confirm.title} body={confirm.body} onCancel={() => setConfirm(null)} onConfirm={() => { confirm.run(); setConfirm(null); }} />;
  }
}
