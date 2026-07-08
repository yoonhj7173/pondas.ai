"use client";

// 인스펙터 사이드 패널(item 24, D15/Flow 4) — 글래스 372px. 팀/에이전트 패널.
import { useState } from "react";
import clsx from "clsx";
import dynamic from "next/dynamic";
import { GlassPanel, PillButton, StatusChip } from "@/components/ui/primitives";
import { STATUS_CHIP, visualStatus } from "@/lib/tokens";
import type { AgentPanelData, TeamPanelData } from "./types";

// 결과 마크다운은 lazy 로드 — react-markdown을 office 기본 청크에서 분리(Phase 2, D51).
const Markdown = dynamic(() => import("@/components/ui/Markdown"), { ssr: false });

function Avatar({ label, color, size = 46 }: { label: string; color?: string; size?: number }) {
  return (
    <div className="flex items-center justify-center rounded-xl font-baloo font-extrabold text-ink"
      style={{ width: size, height: size, background: color ?? "#E2E4D0", fontSize: size * 0.4 }}>
      {label.slice(0, 1).toUpperCase()}
    </div>
  );
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex-1 rounded-xl border border-white/60 bg-white/40 p-3">
      <div className="font-mono text-[10px] uppercase tracking-wider text-muted">{label}</div>
      <div className="font-baloo text-lg font-extrabold">{value}</div>
    </div>
  );
}

/**
 * TeamPanel — 방(팀)을 클릭했을 때 왼쪽에 뜨는 패널. 팀 요약 + 소속 직원 목록 + 추가/삭제 버튼.
 *
 * 무슨 일을 하나: 팀 이름·인원·토큰을 보여주고, 직원 목록에서 한 명을 누르면 그 에이전트 패널로 넘어간다.
 *   '주의 필요'(needs-input/blocked/failed) 인원 수도 표시한다. 화면만 그리고 실제 동작은 콜백으로 위임.
 * 누가 부르나: PanelController(frontend/components/panels/PanelController.tsx)가 sel.kind==="team"일 때.
 */
export function TeamPanel({ data, onClose, onAddAgent, onSelectAgent, onRemove }: {
  data: TeamPanelData; onClose: () => void; onAddAgent: () => void; onSelectAgent: (id: string) => void; onRemove: () => void;
}) {
  const attention = data.agents.filter((a) => ["needs-input", "blocked", "failed"].includes(visualStatus(a.status))).length;
  return (
    <PanelShell onClose={onClose}>
      <div className="flex items-center gap-3">
        <Avatar label={data.name} />
        <div>
          <div className="font-baloo text-xl font-extrabold">{data.name}</div>
          <div className="text-xs text-secondary">{data.agent_count} agents{attention > 0 && ` · ${attention} need attention`}</div>
        </div>
      </div>
      <div className="mt-4 flex gap-3">
        <Tile label="Agents" value={String(data.agent_count)} />
        <Tile label="Tokens" value={data.tokens_total.toLocaleString()} />
      </div>
      <div className="mt-4 space-y-1">
        {data.agents.map((a) => (
          <button key={a.id} onClick={() => onSelectAgent(a.id)} className="flex w-full items-center justify-between rounded-xl bg-white/40 px-3 py-2 hover:bg-white/60">
            <span className="flex items-center gap-2"><Avatar label={a.name} size={28} /><span className="font-nunito text-sm font-bold">{a.name}</span><span className="font-mono text-[10px] text-muted">{a.model_tier}</span></span>
            <StatusChip status={a.status} />
          </button>
        ))}
      </div>
      <div className="mt-5 flex flex-col gap-2">
        <PillButton variant="confirm" onClick={onAddAgent}>+ Add agent</PillButton>
        <PillButton variant="danger" onClick={onRemove}>Remove team</PillButton>
      </div>
    </PanelShell>
  );
}

/**
 * AgentPanel — 직원(에이전트)을 클릭했을 때 뜨는 상세 패널. 상태에 따라 다른 조작 버튼을 보여준다.
 *
 * 무슨 일을 하나: 이름·역할·모델·연결선·토큰·상태를 보여준다. 상태별로 UI가 달라진다:
 *   - 일하는 중(working/queued) → 'Stop task' 버튼.
 *   - 입력 대기(needs-input/blocked) → 에이전트의 질문 + 답 입력칸('Send & resume').
 *   - 실패(failed) → 에러 요약. / 멈춰 있으면 → 'Remove agent'.
 * 누가 부르나: PanelController가 sel.kind==="agent"일 때.
 * 연결: 버튼 동작(onStop/onProvideInput/onRemove) → PanelController → 백엔드 tasks.py/teams.py.
 */
export function AgentPanel({ data, onClose, onStop, onRemove, onProvideInput, onRetry, onViewOutputs, canPreview, onOpenTheater }: {
  data: AgentPanelData; onClose: () => void; onStop: () => void; onRemove: () => void; onProvideInput: (text: string) => void; onRetry: () => void; onViewOutputs?: () => void; canPreview?: boolean; onOpenTheater?: () => void;
}) {
  const v = visualStatus(data.status);
  const headerTint = v === "needs-input" ? "#FBEFCB" : v === "failed" ? "#F8DAD3" : "#DCEEF8";
  const working = data.status === "working" || data.status === "queued";
  const [input, setInput] = useState("");
  return (
    <PanelShell onClose={onClose}>
      <div className="-mx-5 -mt-5 mb-4 rounded-tr-card px-5 pb-4 pt-5" style={{ background: headerTint }}>
        <div className="font-mono text-[10px] uppercase tracking-wider text-secondary">Agent</div>
        <div className="mt-2 flex items-center gap-3">
          <Avatar label={data.name} size={50} />
          <div><div className="font-baloo text-xl font-extrabold">{data.name}</div><StatusChip status={data.status} /></div>
        </div>
      </div>

      <Section title="Role">{data.role_instructions.split("\n")[0]}</Section>
      <div className="mt-3"><Label>Model</Label><span className="inline-block rounded-pill bg-primary-to/20 px-3 py-0.5 text-sm font-bold text-primary-to">{data.model_tier}</span></div>

      <div className="mt-3">
        <Label>Connection</Label>
        {data.outgoing ? (
          <span className={clsx("inline-block rounded-pill px-3 py-0.5 text-xs font-bold", data.outgoing.type === "handoff" ? "bg-primary-to/15 text-primary-to" : "bg-purple-200 text-purple-700")}>
            {data.outgoing.type === "handoff" ? "→ handoff" : `⇄ review loop · max ${data.outgoing.max_iterations}`} · {data.outgoing.to_agent_name}
          </span>
        ) : <span className="text-xs text-muted">Final output (no downstream)</span>}
      </div>

      <div className="mt-4 flex gap-3">
        <Tile label="Tokens" value={data.tokens_total.toLocaleString()} />
        <Tile label="Status" value={visualStatus(data.status)} />
      </div>

      {data.last_result_markdown && (
        <div className="mt-4">
          <div className="flex items-center justify-between">
            <Label>Result</Label>
            {data.last_output_count > 0 && onViewOutputs && (
              <button onClick={onViewOutputs} className="font-mono text-[10px] font-bold text-primary-to hover:underline">
                View files ({data.last_output_count}) →
              </button>
            )}
          </div>
          <div className="mt-1 max-h-72 overflow-y-auto rounded-xl border border-white/60 bg-white/50 p-3">
            <Markdown>{data.last_result_markdown}</Markdown>
          </div>
        </div>
      )}

      {canPreview && onOpenTheater && (
        <button onClick={onOpenTheater} style={{ background: "var(--dark-hud)" }}
          className="mt-4 flex w-full items-center gap-3 rounded-xl border-2 border-white p-3 text-left text-white shadow-card transition-transform hover:-translate-y-0.5">
          <span className="grid h-9 w-9 flex-none place-items-center rounded-lg bg-white/15 text-lg">▶</span>
          <span className="min-w-0 flex-1">
            <span className="block font-baloo text-sm font-extrabold">Live Preview</span>
            <span className="block truncate text-[11px] text-white/60">See the running app · open theater</span>
          </span>
          <span className="flex-none text-white/50">→</span>
        </button>
      )}

      {(data.status === "needs-input" || data.status === "blocked") && (
        <div className="mt-4 rounded-xl border-2 border-status-needs-input/40 bg-status-needs-input/10 p-3">
          <Label>Provide human input</Label>
          {data.awaiting_prompt && <p className="mt-1 text-sm font-bold text-ink-soft">{data.awaiting_prompt}</p>}
          <textarea value={input} onChange={(e) => setInput(e.target.value)} className="mt-1 w-full rounded-lg border border-white bg-white/70 p-2 text-sm outline-none" rows={2} placeholder="Answer the agent's question…" />
          <PillButton variant="confirm" className="mt-2 w-full" onClick={() => onProvideInput(input)}>Send &amp; resume</PillButton>
        </div>
      )}
      {data.status === "failed" && (
        <div className="mt-4 rounded-xl border-2 border-status-failed/40 bg-status-failed/10 p-3 text-sm text-status-failed">{data.error_summary || "Failed — retry or check the verification record."}</div>
      )}

      <div className="mt-5 flex flex-col gap-2">
        {data.status === "failed" && data.failed_task_id && (
          <PillButton variant="confirm" onClick={onRetry}>↻ Retry task</PillButton>
        )}
        {working && <PillButton variant="danger" onClick={onStop}>■ Stop task</PillButton>}
        {working ? (
          <span className="rounded-pill border-2 border-dashed border-muted-2 py-2 text-center text-sm text-muted">Stop the task before removing</span>
        ) : (
          <button onClick={onRemove} className="rounded-pill border-2 border-status-failed/50 py-2 text-sm font-bold text-status-failed transition-colors hover:bg-status-failed/10">Remove agent</button>
        )}
      </div>
    </PanelShell>
  );
}

function PanelShell({ children, onClose }: { children: React.ReactNode; onClose: () => void }) {
  return (
    <div className="absolute left-0 top-0 z-40 h-full">
      <GlassPanel className="h-full overflow-y-auto rounded-none">
        <button onClick={onClose} className="absolute right-4 top-4 text-lg text-muted hover:text-ink">×</button>
        {children}
      </GlassPanel>
    </div>
  );
}
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <div className="mt-3"><Label>{title}</Label><div className="text-sm text-ink-soft">{children}</div></div>;
}
function Label({ children }: { children: React.ReactNode }) {
  return <div className="font-mono text-[10px] uppercase tracking-wider text-muted">{children}</div>;
}
