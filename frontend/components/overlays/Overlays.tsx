"use client";

// 오버레이(item 25) — Board · Settings · Outputs. HUD 유틸 버튼이 연다.
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import clsx from "clsx";
import dynamic from "next/dynamic";
import { Overlay, PillButton } from "@/components/ui/primitives";
import { apiFetch, API_BASE } from "@/lib/api";
import { visualStatus, type AgentStatus } from "@/lib/tokens";

// 결과 마크다운 렌더러 — lazy 로드(office 기본 청크 분리, Phase 2 D51).
const Markdown = dynamic(() => import("@/components/ui/Markdown"), { ssr: false });
const MARKDOWN_EXTS = /\.(md|markdown|mdx)$/i;

export type OverlayKind = "board" | "settings" | "outputs" | null;

const STATUS_ICON: Record<string, { glyph: string; cls: string }> = {
  done: { glyph: "✓", cls: "bg-status-done text-white" },
  working: { glyph: "●", cls: "border-2 border-status-working text-status-working" },
  queued: { glyph: "○", cls: "border-2 border-muted-2 text-muted" },
  "needs-input": { glyph: "!", cls: "bg-status-needs-input text-white" },
  failed: { glyph: "×", cls: "bg-status-failed text-white" },
  idle: { glyph: "○", cls: "border-2 border-muted-2 text-muted" },
};

// --- Board ---
interface BoardData { goals: { id: string | null; title: string; tasks: { id: string; agent_id: string; agent_name: string; status: AgentStatus; instructions: string }[] }[] }

/**
 * BoardOverlay — '작업 계획' 전체화면 오버레이. 목표별로 묶인 작업들을 칸반처럼 펼쳐 보여준다.
 *
 * 무슨 일을 하나: /board를 불러 목표×작업을 그린다. 진행 중/실패/입력대기 작업은 눌러서 해당 에이전트로
 *   포커스 이동. 누가 부르나: HUD 유틸의 'Board' 버튼 → ProjectMap. 연결: backend/app/routers/realtime.py의 board.
 */
export function BoardOverlay({ projectId, getToken, onClose, onFocus }: { projectId: string; getToken: () => Promise<string | null>; onClose: () => void; onFocus: (id: string) => void }) {
  const [data, setData] = useState<BoardData | null>(null);
  useEffect(() => { (async () => setData(await apiFetch(`/api/projects/${projectId}/board`, { token: await getToken() })))().catch(() => setData({ goals: [] })); }, [projectId, getToken]);
  return (
    <Overlay onClose={onClose}>
      <div className="w-[840px] max-w-[92vw] p-7">
        <Title onClose={onClose}>Work plan</Title>
        <div className="mt-4 max-h-[60vh] space-y-5 overflow-y-auto">
          {data?.goals.length === 0 && <Empty>No work yet — dispatch something from the chat.</Empty>}
          {data?.goals.map((g) => (
            <div key={g.id ?? "none"}>
              <div className="mb-2 flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full bg-primary-to" /><span className="font-baloo font-extrabold">{g.title}</span></div>
              <div className="space-y-1">
                {g.tasks.map((t) => {
                  const v = visualStatus(t.status); const ic = STATUS_ICON[v] ?? STATUS_ICON.idle;
                  const focusable = v === "working" || v === "failed" || v === "needs-input";
                  return (
                    <button key={t.id} disabled={!focusable} onClick={() => onFocus(t.agent_id)} className={clsx("flex w-full items-center gap-3 rounded-xl bg-white/40 px-3 py-2 text-left", focusable && "hover:bg-white/60")}>
                      <span className={clsx("flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold", ic.cls)}>{ic.glyph}</span>
                      <span className="flex-1 truncate text-sm">{t.instructions}</span>
                      <span className="font-mono text-[10px] text-muted">{t.agent_name} · {v}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </div>
    </Overlay>
  );
}

// --- Outputs ---
interface OutGroup { task_id: string; agent_name: string; file_count: number; files: { id: string; path: string; mime: string; size_bytes: number }[] }

/**
 * OutputsOverlay — '결과물' 전체화면 오버레이. 왼쪽에 작업별 파일 목록, 오른쪽에 미리보기.
 *
 * 무슨 일을 하나: /outputs로 작업별 파일 트리를 받아 보여주고, 파일을 누르면 /outputs/{id}로 내용을
 *   불러 오른쪽에 미리본다(바이너리는 다운로드 안내). 작업별 zip 다운로드 링크도 제공.
 * 누가 부르나: HUD 유틸의 'Outputs' 버튼. 연결: backend/app/routers/outputs.py.
 */
export function OutputsOverlay({ projectId, getToken, onClose }: { projectId: string; getToken: () => Promise<string | null>; onClose: () => void }) {
  const [groups, setGroups] = useState<OutGroup[] | null>(null);
  const [sel, setSel] = useState<{ id: string; path: string } | null>(null);
  const [preview, setPreview] = useState<{ content: string | null; is_binary: boolean } | null>(null);

  useEffect(() => { (async () => setGroups(await apiFetch(`/api/projects/${projectId}/outputs`, { token: await getToken() })))().catch(() => setGroups([])); }, [projectId, getToken]);
  useEffect(() => { if (!sel) return; (async () => setPreview(await apiFetch(`/api/outputs/${sel.id}`, { token: await getToken() })))().catch(() => {}); }, [sel, getToken]);

  return (
    <Overlay onClose={onClose}>
      <div className="flex h-[600px] w-[960px] max-w-[94vw] flex-col p-7">
        <Title onClose={onClose}>Outputs</Title>
        <div className="mt-4 flex min-h-0 flex-1 gap-4">
          <div className="w-1/2 space-y-3 overflow-y-auto pr-2">
            {groups?.length === 0 && <Empty>No outputs yet.</Empty>}
            {groups?.map((g) => (
              <div key={g.task_id} className="rounded-xl bg-white/40 p-3">
                <div className="mb-1 flex items-center justify-between"><span className="font-baloo text-sm font-bold">{g.agent_name}</span><a href={`${API_BASE}/api/tasks/${g.task_id}/outputs.zip`} className="text-xs font-bold text-primary-to">⇩ zip</a></div>
                {g.files.map((f) => (
                  <button key={f.id} onClick={() => setSel({ id: f.id, path: f.path })} className={clsx("flex w-full items-center justify-between rounded px-2 py-1 text-left font-mono text-xs hover:bg-white/60", sel?.id === f.id && "bg-white/70")}>
                    <span className="truncate">{f.path}</span><span className="text-muted">{f.size_bytes}b</span>
                  </button>
                ))}
              </div>
            ))}
          </div>
          <div className="w-1/2 overflow-auto rounded-xl bg-[#1F2430] p-3 text-white">
            {!sel && <div className="p-4 text-sm opacity-40">Select a file to preview</div>}
            {preview?.is_binary && <div className="p-4 text-sm opacity-60">Binary file — download to view.</div>}
            {preview?.content != null && (
              sel && MARKDOWN_EXTS.test(sel.path)
                ? <Markdown className="prose-result prose-result-dark">{preview.content}</Markdown>
                : <pre className="h-full overflow-auto whitespace-pre-wrap font-mono text-[11px] leading-relaxed">{preview.content}</pre>
            )}
          </div>
        </div>
      </div>
    </Overlay>
  );
}

// --- Settings ---
/**
 * SettingsOverlay — '설정' 전체화면 오버레이. 탭으로 컨텍스트·메모리·가드레일·프로젝트를 관리한다.
 *
 * 무슨 일을 하나: 좌측 탭으로 나뉜 설정 화면. 가드레일 탭에서 하루 비용/동시실행 한도를 조절하고,
 *   프로젝트 일시정지를 켜고 끈다(켜면 자동 전파까지 전부 멈춤). 프로젝트 탭에서 이름변경·삭제.
 * 누가 부르나: HUD 유틸의 'Settings' 버튼. 연결: 일시정지 → backend/app/routers/projects.py의 pause/resume.
 */
export function SettingsOverlay({ projectId, getToken, projectName, paused, onClose, onChanged }: { projectId: string; getToken: () => Promise<string | null>; projectName: string; paused: boolean; onClose: () => void; onChanged: () => void }) {
  const [tab, setTab] = useState<"context" | "memory" | "guardrails" | "project">("guardrails");
  const [cost, setCost] = useState(10);
  const [conc, setConc] = useState(3);
  const [isPaused, setIsPaused] = useState(paused);
  const [danger, setDanger] = useState<null | "project" | "account">(null);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [dangerErr, setDangerErr] = useState<string | null>(null);
  const router = useRouter();
  const { signOut } = useAuth();

  async function togglePause() {
    const next = !isPaused; setIsPaused(next);
    await apiFetch(`/api/projects/${projectId}/${next ? "pause" : "resume"}`, { method: "POST", token: await getToken() }).catch(() => {});
    onChanged();
  }

  // 삭제는 성공했을 때만 이동/로그아웃 — 실패 시 데이터가 남았는데 유저를 내보내면 안 됨(거짓 성공 금지).
  async function deleteProject() {
    if (busy) return;
    setBusy(true); setDangerErr(null);
    try {
      await apiFetch(`/api/projects/${projectId}`, { method: "DELETE", token: await getToken() });
    } catch (e) {
      setBusy(false);
      setDangerErr(e instanceof Error ? e.message : "Couldn't delete the project — try again");
      return;
    }
    router.push("/app"); // /app 인덱스가 다른 프로젝트 or 온보딩으로 보냄
  }

  async function deleteAccount() {
    if (busy) return;
    setBusy(true); setDangerErr(null);
    try {
      await apiFetch(`/api/account`, { method: "DELETE", token: await getToken() });
    } catch (e) {
      setBusy(false);
      setDangerErr(e instanceof Error ? e.message : "Couldn't delete your account — try again");
      return;  // 실패 → 로그아웃/이동 안 함(계정 남았는데 잠기는 것 방지).
    }
    try { await signOut?.(); } catch { /* Clerk 유저 이미 삭제됨 */ }
    router.push("/");
  }

  return (
    <Overlay onClose={onClose}>
      <div className="flex h-[600px] w-[860px] max-w-[94vw] flex-col p-0">
        <div className="flex flex-1 min-h-0">
          <div className="w-48 shrink-0 space-y-1 border-r border-white/40 bg-white/30 p-4">
            <div className="mb-3 font-baloo text-lg font-extrabold">Settings</div>
            {(["context", "memory", "guardrails", "project"] as const).map((t) => (
              <button key={t} onClick={() => setTab(t)} className={clsx("block w-full rounded-lg px-3 py-2 text-left text-sm font-bold capitalize", tab === t ? "bg-primary-to text-white" : "text-secondary hover:bg-white/40")}>{t}</button>
            ))}
          </div>
          <div className="flex-1 overflow-y-auto p-6">
            {tab === "guardrails" && (
              <div className="space-y-6">
                <Stepper label="Daily cost cap" value={`$${cost}`} onDec={() => setCost((c) => Math.max(10, c - 10))} onInc={() => setCost((c) => Math.min(100, c + 10))} />
                <Stepper label="Concurrency cap" value={String(conc)} onDec={() => setConc((c) => Math.max(1, c - 1))} onInc={() => setConc((c) => Math.min(5, c + 1))} />
                <div className="flex items-center justify-between rounded-xl border-2 border-status-failed/40 bg-status-failed/10 px-4 py-3">
                  <div><div className="font-baloo font-bold text-status-failed">Pause project</div><div className="text-xs text-secondary">Halts all dispatching including edge auto-fires.</div></div>
                  <button onClick={togglePause} className={clsx("h-7 w-12 rounded-full p-0.5 transition", isPaused ? "bg-status-failed" : "bg-muted-2")}><span className={clsx("block h-6 w-6 rounded-full bg-white transition", isPaused && "translate-x-5")} /></button>
                </div>
              </div>
            )}
            {tab === "context" && <Empty>Upload project context files (txt/md/pdf).</Empty>}
            {tab === "memory" && <Empty>Per-agent memory scratchpads — view / edit / clear.</Empty>}
            {tab === "project" && (
              <div className="space-y-4">
                <div><Lbl>Project name</Lbl><input defaultValue={projectName} className="mt-1 w-full max-w-sm rounded-pill border-2 border-white bg-white/70 px-4 py-2 outline-none" /></div>
                <div className="space-y-3 rounded-xl border-2 border-status-failed/40 bg-status-failed/10 p-4">
                  <div className="font-baloo font-bold text-status-failed">Danger zone</div>

                  {/* 프로젝트 삭제 */}
                  {danger === "project" ? (
                    <div className="flex items-center gap-2 text-sm">
                      <span className="text-status-failed">Delete “{projectName}” and everything in it?</span>
                      <PillButton variant="danger" onClick={deleteProject} disabled={busy}>{busy ? "Deleting…" : "Delete"}</PillButton>
                      <button className="text-secondary hover:underline" onClick={() => setDanger(null)}>Cancel</button>
                    </div>
                  ) : (
                    <PillButton variant="danger" onClick={() => { setDanger("project"); setTyped(""); }}>Delete project</PillButton>
                  )}

                  <div className="border-t border-status-failed/20 pt-3">
                    <div className="text-xs text-secondary">Delete your account — all projects, remaining credits, and sign-in. This cannot be undone.</div>
                    {danger === "account" ? (
                      <div className="mt-2 space-y-2">
                        <div className="text-sm text-status-failed">Type <b>DELETE</b> to confirm permanent account deletion:</div>
                        <input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="DELETE"
                          className="w-40 rounded-pill border-2 border-status-failed/40 bg-white/70 px-3 py-1.5 text-sm outline-none" />
                        <div className="flex items-center gap-2">
                          <PillButton variant="danger" onClick={deleteAccount} disabled={busy || typed !== "DELETE"}>{busy ? "Deleting…" : "Delete my account"}</PillButton>
                          <button className="text-secondary hover:underline" onClick={() => { setDanger(null); setTyped(""); }}>Cancel</button>
                        </div>
                      </div>
                    ) : (
                      <button className="mt-2 text-sm font-bold text-status-failed hover:underline" onClick={() => setDanger("account")}>Delete account</button>
                    )}
                  </div>

                  {dangerErr && <div className="rounded-lg bg-status-failed/15 px-3 py-2 text-xs font-bold text-status-failed">{dangerErr}</div>}
                </div>
              </div>
            )}
          </div>
        </div>
        <div className="flex items-center justify-end gap-4 border-t border-white/40 px-6 py-3 text-xs text-secondary">
          <button onClick={onClose}>Close</button>
        </div>
      </div>
    </Overlay>
  );
}

function Stepper({ label, value, onDec, onInc }: { label: string; value: string; onDec: () => void; onInc: () => void }) {
  return (
    <div>
      <Lbl>{label}</Lbl>
      <div className="mt-1 flex items-center gap-3">
        <button onClick={onDec} className="h-9 w-9 rounded-full bg-white/70 text-lg font-bold">−</button>
        <span className="w-16 text-center font-baloo text-lg font-extrabold">{value}</span>
        <button onClick={onInc} className="h-9 w-9 rounded-full bg-white/70 text-lg font-bold">+</button>
      </div>
    </div>
  );
}
function Title({ children, onClose }: { children: React.ReactNode; onClose: () => void }) {
  return <div className="flex items-center justify-between"><span className="font-baloo text-2xl font-extrabold">{children}</span><button onClick={onClose} className="text-lg text-muted">×</button></div>;
}
function Empty({ children }: { children: React.ReactNode }) { return <div className="py-8 text-center text-sm text-muted">{children}</div>; }
function Lbl({ children }: { children: React.ReactNode }) { return <div className="font-mono text-[10px] uppercase tracking-wider text-muted">{children}</div>; }
