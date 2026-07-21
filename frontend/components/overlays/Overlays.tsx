"use client";

// 오버레이(item 25) — Board · Settings · Outputs. HUD 유틸 버튼이 연다.
import { useCallback, useEffect, useRef, useState } from "react";
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

export type OverlayKind = "board" | "settings" | "outputs" | "notes" | "history" | null;

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
  const [tab, setTab] = useState<"context" | "memory" | "project">("context");
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
            {(["context", "memory", "project"] as const).map((t) => (
              <button key={t} onClick={() => setTab(t)} className={clsx("block w-full rounded-lg px-3 py-2 text-left text-sm font-bold capitalize", tab === t ? "bg-primary-to text-white" : "text-secondary hover:bg-white/40")}>{t}</button>
            ))}
          </div>
          <div className="flex-1 overflow-y-auto p-6">
            {tab === "context" && <ContextManager projectId={projectId} getToken={getToken} />}
            {tab === "memory" && <MemoryManager projectId={projectId} getToken={getToken} />}
            {tab === "project" && (
              <div className="space-y-4">
                <ProjectRename projectId={projectId} projectName={projectName} getToken={getToken} onChanged={onChanged} />
                {/* 프로젝트 일시정지 — 유일하게 남은 실제 프로젝트 컨트롤(cost/concurrency 캡은 크레딧이 이미 상한이라 제거). */}
                <div className="flex items-center justify-between rounded-xl border-2 border-status-failed/40 bg-status-failed/10 px-4 py-3">
                  <div><div className="font-baloo font-bold text-status-failed">Pause project</div><div className="text-xs text-secondary">Halts all dispatching including edge auto-fires.</div></div>
                  <button onClick={togglePause} className={clsx("h-7 w-12 rounded-full p-0.5 transition", isPaused ? "bg-status-failed" : "bg-muted-2")}><span className={clsx("block h-6 w-6 rounded-full bg-white transition", isPaused && "translate-x-5")} /></button>
                </div>
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

// --- Settings: 프로젝트 이름 변경(백엔드 PATCH /projects/{id} 배선) ---
function ProjectRename({ projectId, projectName, getToken, onChanged }: { projectId: string; projectName: string; getToken: () => Promise<string | null>; onChanged: () => void }) {
  const [name, setName] = useState(projectName);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const dirty = name.trim() !== projectName && name.trim().length > 0;

  async function save() {
    if (!dirty || busy) return;
    setBusy(true); setErr(null); setSaved(false);
    try {
      await apiFetch(`/api/projects/${projectId}`, { method: "PATCH", token: await getToken(), body: JSON.stringify({ name: name.trim() }) });
      setSaved(true); onChanged();
    } catch (e) { setErr(e instanceof Error ? e.message : "Couldn't save the name"); }
    finally { setBusy(false); }
  }

  return (
    <div>
      <Lbl>Project name</Lbl>
      <div className="mt-1 flex items-center gap-2">
        <input value={name} maxLength={200} onChange={(e) => { setName(e.target.value); setSaved(false); }}
          className="w-full max-w-sm rounded-pill border-2 border-white bg-white/70 px-4 py-2 outline-none" />
        <PillButton variant="confirm" disabled={!dirty || busy} onClick={save}>{busy ? "Saving…" : "Save"}</PillButton>
        {saved && <span className="text-xs font-bold text-status-done">Saved ✓</span>}
      </div>
      {err && <div className="mt-1 text-xs font-bold text-status-failed">{err}</div>}
    </div>
  );
}

// --- Settings: 프로젝트 컨텍스트 파일(업로드/목록/삭제). 온보딩과 같은 백엔드 경로(보안 동일). ---
interface ContextFileRow { id: string; filename: string; mime: string; size_bytes: number }
function ContextManager({ projectId, getToken }: { projectId: string; getToken: () => Promise<string | null> }) {
  const [files, setFiles] = useState<ContextFileRow[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try { setFiles(await apiFetch<ContextFileRow[]>(`/api/projects/${projectId}/context`, { token: await getToken() })); }
    catch { setFiles([]); }
  }, [projectId, getToken]);
  useEffect(() => { load(); }, [load]);

  async function upload(list: FileList | null) {
    if (!list?.length) return;
    setBusy(true); setErr(null);
    try {
      for (const f of Array.from(list)) {
        const fd = new FormData(); fd.append("file", f);
        await apiFetch(`/api/projects/${projectId}/context`, { method: "POST", token: await getToken(), body: fd });
      }
      await load();
    } catch (e) { setErr(e instanceof Error ? e.message : "Upload failed"); }
    finally { setBusy(false); if (inputRef.current) inputRef.current.value = ""; }
  }

  async function del(id: string) {
    setErr(null);
    try { await apiFetch(`/api/context/${id}`, { method: "DELETE", token: await getToken() }); await load(); }
    catch (e) { setErr(e instanceof Error ? e.message : "Couldn't remove the file"); }
  }

  return (
    <div className="space-y-4">
      <div>
        <Lbl>Project context</Lbl>
        <p className="mt-1 text-xs text-secondary">Files (txt, md, pdf · ≤ 10 MB) your agents can read — the extracted text is injected into their prompts.</p>
      </div>
      <div>
        <input ref={inputRef} type="file" accept=".txt,.md,.markdown,.pdf" multiple className="hidden" onChange={(e) => upload(e.target.files)} />
        <PillButton variant="primary" disabled={busy} onClick={() => inputRef.current?.click()}>{busy ? "Uploading…" : "+ Upload files"}</PillButton>
      </div>
      {err && <div className="rounded-lg bg-status-failed/15 px-3 py-2 text-xs font-bold text-status-failed">{err}</div>}
      <div className="space-y-2">
        {files === null && <div className="text-sm text-secondary">Loading…</div>}
        {files?.length === 0 && <Empty>No context files yet.</Empty>}
        {files?.map((f) => (
          <div key={f.id} className="flex items-center justify-between rounded-xl border-2 border-white bg-white/60 px-4 py-2">
            <div className="min-w-0">
              <div className="truncate text-sm font-bold">{f.filename}</div>
              <div className="font-mono text-[10px] text-muted">{f.mime} · {(f.size_bytes / 1024).toFixed(1)} KB</div>
            </div>
            <button onClick={() => del(f.id)} className="shrink-0 text-sm font-bold text-status-failed hover:underline">Remove</button>
          </div>
        ))}
      </div>
    </div>
  );
}

// --- Settings: 에이전트별 메모리(보기/수정/비우기). 목록은 /map에서 에이전트를 가져온다. ---
function MemoryManager({ projectId, getToken }: { projectId: string; getToken: () => Promise<string | null> }) {
  const [agents, setAgents] = useState<{ id: string; name: string; team: string }[] | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const map = await apiFetch<{ teams: { name: string; agents: { id: string; name: string }[] }[] }>(`/api/projects/${projectId}/map`, { token: await getToken() });
        if (alive) setAgents(map.teams.flatMap((t) => t.agents.map((a) => ({ id: a.id, name: a.name, team: t.name }))));
      } catch { if (alive) setAgents([]); }
    })();
    return () => { alive = false; };
  }, [projectId, getToken]);

  return (
    <div className="space-y-4">
      <div>
        <Lbl>Agent memory</Lbl>
        <p className="mt-1 text-xs text-secondary">Each agent keeps a markdown scratchpad it carries between tasks. View, edit, or clear it here.</p>
      </div>
      {agents === null && <div className="text-sm text-secondary">Loading…</div>}
      {agents?.length === 0 && <Empty>No agents yet — hire some first.</Empty>}
      <div className="space-y-2">
        {agents?.map((a) => (
          <div key={a.id} className="rounded-xl border-2 border-white bg-white/60">
            <button onClick={() => setOpenId((o) => (o === a.id ? null : a.id))} className="flex w-full items-center justify-between px-4 py-2 text-left">
              <span className="text-sm font-bold">{a.name} <span className="font-mono text-[10px] text-muted">· {a.team}</span></span>
              <span className="text-muted">{openId === a.id ? "▾" : "▸"}</span>
            </button>
            {openId === a.id && <MemoryEditor agentId={a.id} getToken={getToken} />}
          </div>
        ))}
      </div>
    </div>
  );
}

function MemoryEditor({ agentId, getToken }: { agentId: string; getToken: () => Promise<string | null> }) {
  const [content, setContent] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const m = await apiFetch<{ content_md: string }>(`/api/agents/${agentId}/memory`, { token: await getToken() });
        if (alive) setContent(m.content_md);
      } catch { if (alive) setContent(""); }
    })();
    return () => { alive = false; };
  }, [agentId, getToken]);

  async function save() {
    if (content === null || busy) return;
    setBusy(true); setErr(null); setSaved(false);
    try { await apiFetch(`/api/agents/${agentId}/memory`, { method: "PUT", token: await getToken(), body: JSON.stringify({ content_md: content }) }); setSaved(true); }
    catch (e) { setErr(e instanceof Error ? e.message : "Couldn't save"); }
    finally { setBusy(false); }
  }
  async function clear() {
    setBusy(true); setErr(null); setSaved(false);
    try { await apiFetch(`/api/agents/${agentId}/memory`, { method: "DELETE", token: await getToken() }); setContent(""); }
    catch (e) { setErr(e instanceof Error ? e.message : "Couldn't clear"); }
    finally { setBusy(false); }
  }

  if (content === null) return <div className="px-4 pb-3 text-xs text-secondary">Loading…</div>;
  return (
    <div className="space-y-2 border-t border-white/50 px-4 py-3">
      <textarea value={content} maxLength={20000} onChange={(e) => { setContent(e.target.value); setSaved(false); }} rows={5}
        placeholder="Empty — this agent has no saved memory yet." className="w-full rounded-lg border-2 border-white bg-white/70 p-2 text-xs outline-none" />
      <div className="flex items-center gap-2">
        <PillButton variant="confirm" disabled={busy} onClick={save}>{busy ? "Saving…" : "Save"}</PillButton>
        <button onClick={clear} disabled={busy} className="text-xs font-bold text-status-failed hover:underline">Clear</button>
        {saved && <span className="text-xs font-bold text-status-done">Saved ✓</span>}
        {err && <span className="text-xs font-bold text-status-failed">{err}</span>}
      </div>
    </div>
  );
}

// --- Notes (Board 밑 Notes 메뉴, issue 4) — 텍스트 전용 노트. 리스트 + 편집 + 마크다운 프리뷰. ---
interface NoteRow { id: string; title: string; body: string; updated_at: string }
export function NotesOverlay({ projectId, getToken, onClose }: { projectId: string; getToken: () => Promise<string | null>; onClose: () => void }) {
  const [notes, setNotes] = useState<NoteRow[] | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);

  const load = useCallback(async () => {
    try { const rows = await apiFetch<NoteRow[]>(`/api/projects/${projectId}/notes`, { token: await getToken() }); setNotes(rows); return rows; }
    catch { setNotes([]); return [] as NoteRow[]; }
  }, [projectId, getToken]);
  useEffect(() => { load(); }, [load]);

  function openNote(n: NoteRow) { setSel(n.id); setTitle(n.title); setBody(n.body); setSaved(false); }

  async function createNote() {
    setBusy(true);
    try {
      const n = await apiFetch<NoteRow>(`/api/projects/${projectId}/notes`, { method: "POST", token: await getToken(), body: JSON.stringify({ title: "", body: "" }) });
      await load(); openNote(n);
    } catch { /* noop */ } finally { setBusy(false); }
  }
  async function save() {
    if (!sel) return;
    setBusy(true); setSaved(false);
    try { await apiFetch(`/api/notes/${sel}`, { method: "PATCH", token: await getToken(), body: JSON.stringify({ title, body }) }); await load(); setSaved(true); }
    catch { /* noop */ } finally { setBusy(false); }
  }
  async function del(id: string) {
    setBusy(true);
    try { await apiFetch(`/api/notes/${id}`, { method: "DELETE", token: await getToken() }); await load(); if (sel === id) setSel(null); }
    catch { /* noop */ } finally { setBusy(false); }
  }

  return (
    <Overlay onClose={onClose}>
      <div className="flex h-[600px] w-[900px] max-w-[94vw] flex-col p-0">
        <div className="border-b border-white/40 px-6 py-4"><Title onClose={onClose}>Notes</Title></div>
        <div className="flex min-h-0 flex-1">
          <div className="flex w-56 shrink-0 flex-col border-r border-white/40 bg-white/30 p-3">
            <PillButton variant="primary" onClick={createNote} disabled={busy}>+ New note</PillButton>
            <div className="mt-2 min-h-0 flex-1 space-y-1 overflow-y-auto">
              {notes === null && <div className="px-1 py-2 text-sm text-secondary">Loading…</div>}
              {notes?.length === 0 && <div className="px-1 py-2 text-xs text-muted">No notes yet.</div>}
              {notes?.map((n) => (
                <button key={n.id} onClick={() => openNote(n)} className={clsx("block w-full truncate rounded-lg px-3 py-2 text-left text-sm font-bold", sel === n.id ? "bg-primary-to text-white" : "text-secondary hover:bg-white/40")}>
                  {n.title.trim() || "Untitled"}
                </button>
              ))}
            </div>
          </div>
          <div className="flex-1 overflow-y-auto p-6">
            {sel === null ? (
              <div className="flex h-full items-center justify-center text-sm text-muted">Select a note, or create one.</div>
            ) : (
              <div className="space-y-3">
                <input value={title} maxLength={200} onChange={(e) => { setTitle(e.target.value); setSaved(false); }} placeholder="Untitled"
                  className="w-full rounded-pill border-2 border-white bg-white/70 px-4 py-2 font-baloo text-lg font-extrabold outline-none" />
                <textarea value={body} maxLength={20000} onChange={(e) => { setBody(e.target.value); setSaved(false); }} rows={11}
                  placeholder={"Write freely. Lists render:\n- a bullet\n1. a numbered item"}
                  className="w-full rounded-xl border-2 border-white bg-white/70 p-3 text-sm outline-none" />
                <div className="flex items-center gap-2">
                  <PillButton variant="confirm" onClick={save} disabled={busy}>{busy ? "Saving…" : "Save"}</PillButton>
                  <button onClick={() => del(sel)} disabled={busy} className="text-sm font-bold text-status-failed hover:underline">Delete</button>
                  {saved && <span className="text-xs font-bold text-status-done">Saved ✓</span>}
                </div>
                {body.trim() && (
                  <div className="rounded-xl border-2 border-white/60 bg-white/40 p-4">
                    <div className="mb-2 font-mono text-[10px] uppercase tracking-wide text-muted">Preview</div>
                    <Markdown>{body}</Markdown>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </Overlay>
  );
}

function Title({ children, onClose }: { children: React.ReactNode; onClose: () => void }) {
  return <div className="flex items-center justify-between"><span className="font-baloo text-2xl font-extrabold">{children}</span><button onClick={onClose} className="text-lg text-muted">×</button></div>;
}
function Empty({ children }: { children: React.ReactNode }) { return <div className="py-8 text-center text-sm text-muted">{children}</div>; }
function Lbl({ children }: { children: React.ReactNode }) { return <div className="font-mono text-[10px] uppercase tracking-wider text-muted">{children}</div>; }

// --- History (item 36, D61) ---

interface HistoryData {
  repo_full_name: string | null;
  versions: { version_no: number; label: string; created_at: string; pushed: boolean; commit_sha: string | null; files: number }[];
}
interface GithubStatus { enabled: boolean; install_url: string | null; authorize_url?: string | null; connected: boolean; has_user_token?: boolean; account_login: string | null }

/**
 * HistoryOverlay — 사람말 버전 히스토리 + Restore + GitHub 연결 카드(D61).
 *
 * 무슨 일을 하나: 버전 목록(라벨 + 푸시 상태)을 보여주고, Restore로 과거 시점을 새 버전으로
 *   복원한다(히스토리 보존). 상단 카드에서 GitHub 연결/리포 생성("네 코드는 처음부터 네 것").
 * 누가 부르나: HUD 유틸의 'History' 버튼. 연결: backend/app/routers/github.py.
 */
export function HistoryOverlay({ projectId, getToken, onClose }: { projectId: string; getToken: () => Promise<string | null>; onClose: () => void }) {
  const [data, setData] = useState<HistoryData | null>(null);
  const [gh, setGh] = useState<GithubStatus | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [repoBusy, setRepoBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 코드뷰(D56④) — "숨기되 잠그지 않기": 원하면 최신 버전 파일을 읽을 수 있다.
  const [tab, setTab] = useState<"history" | "code">("history");
  const [files, setFiles] = useState<{ path: string; output_id: string }[] | null>(null);
  const [fileView, setFileView] = useState<{ path: string; content: string | null; binary: boolean } | null>(null);

  async function loadFiles() {
    const token = await getToken();
    const res = await apiFetch<{ version_no: number | null; files: { path: string; output_id: string }[] }>(
      `/api/projects/${projectId}/files`, { token });
    setFiles(res.files);
  }
  async function openFile(f: { path: string; output_id: string }) {
    const token = await getToken();
    const res = await apiFetch<{ path: string; is_binary: boolean; content: string | null }>(
      `/api/outputs/${f.output_id}`, { token });
    setFileView({ path: res.path, content: res.content, binary: res.is_binary });
  }

  const load = useCallback(async () => {
    const token = await getToken();
    const [h, s] = await Promise.all([
      apiFetch<HistoryData>(`/api/projects/${projectId}/history`, { token }),
      apiFetch<GithubStatus>(`/api/github/status`, { token }),
    ]);
    setData(h); setGh(s);
  }, [projectId, getToken]);
  useEffect(() => { load().catch(() => setError("Failed to load history")); }, [load]);

  async function restore(no: number) {
    if (!window.confirm(`Restore the workspace to v${no}? This creates a new version — nothing is deleted.`)) return;
    setBusy(no); setError(null);
    try {
      const token = await getToken();
      await apiFetch(`/api/projects/${projectId}/restore/${no}`, { method: "POST", token });
      await load();
    } catch { setError("Restore failed — try again"); } finally { setBusy(null); }
  }

  async function createRepo() {
    setRepoBusy(true); setError(null);
    try {
      const token = await getToken();
      await apiFetch(`/api/projects/${projectId}/repo`, { method: "POST", token });
      await load();
    } catch (e) {
      const msg = e instanceof Error && e.message.includes("reconnect")
        ? "Please reconnect GitHub once more (we need a fresh authorization to create repos)."
        : "Could not create the repository";
      setError(msg);
    } finally { setRepoBusy(false); }
  }

  return (
    <Overlay onClose={onClose}>
      <div className="flex h-[600px] w-[720px] flex-col p-6">
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <h2 className="text-xl font-bold">Version history</h2>
            <button onClick={() => setTab("history")}
              className={clsx("rounded-pill px-3 py-1 text-[12px] font-semibold", tab === "history" ? "bg-primary-to text-white" : "bg-[#EFEDF5] text-secondary")}>Versions</button>
            <button onClick={() => { setTab("code"); if (!files) loadFiles().catch(() => setError("Failed to load files")); }}
              className={clsx("rounded-pill px-3 py-1 text-[12px] font-semibold", tab === "code" ? "bg-primary-to text-white" : "bg-[#EFEDF5] text-secondary")}>View code</button>
          </div>
          <button onClick={onClose} className="text-sm text-muted hover:underline">Close</button>
        </div>

        {/* GitHub 소유권 카드(D61) — 신뢰 표면: 크롬 전용, 월드 요소 없음(D59). */}
        <div className="mb-4 flex items-center justify-between rounded-xl border border-[#E4DFEF] bg-[#FDFCF9] px-4 py-3 text-sm">
          {!gh ? <span className="text-muted">Loading…</span> : !gh.enabled ? (
            <span className="text-muted">GitHub sync isn&apos;t configured on this server yet.</span>
          ) : data?.repo_full_name ? (
            <>
              <span>Synced to <a className="font-semibold text-primary-to hover:underline" href={`https://github.com/${data.repo_full_name}`} target="_blank" rel="noreferrer">{data.repo_full_name}</a> — your code, your repo.</span>
              <span className="text-[11px] text-muted">connected as {gh.account_login}</span>
            </>
          ) : gh.connected && !gh.has_user_token ? (
            <>
              <span>Connected as <b>{gh.account_login}</b> — one more click to allow repo creation.</span>
              <a href={gh.authorize_url ?? "#"}>
                <PillButton variant="primary" className="!px-4 !py-1.5 text-[13px]">Authorize repos</PillButton>
              </a>
            </>
          ) : gh.connected ? (
            <>
              <span>Connected as <b>{gh.account_login}</b>. Create a repository to own every version.</span>
              <PillButton variant="primary" className="!px-4 !py-1.5 text-[13px]" onClick={createRepo} disabled={repoBusy}>{repoBusy ? "Creating…" : "Create repository"}</PillButton>
            </>
          ) : (
            <>
              <span>Own your code — every version becomes a commit in <b>your</b> GitHub repo.</span>
              <a href={gh.install_url ?? "#"} target="_blank" rel="noreferrer">
                <PillButton variant="primary" className="!px-4 !py-1.5 text-[13px]">Connect GitHub</PillButton>
              </a>
            </>
          )}
        </div>

        {error && <div className="mb-2 text-sm text-status-failed">{error}</div>}

        {tab === "code" ? (
          <div className="flex min-h-0 flex-1 gap-3">
            <div className="chat-scroll w-56 flex-none overflow-y-auto rounded-xl border border-[#F0EDF6] p-2">
              {!files ? <div className="py-4 text-center text-[12px] text-muted">Loading…</div> :
                files.length === 0 ? <div className="py-4 text-center text-[12px] text-muted">No files yet</div> :
                files.map((f) => (
                  <button key={f.path} onClick={() => openFile(f)}
                    className={clsx("block w-full truncate rounded-md px-2 py-1 text-left font-mono text-[11px] hover:bg-[#F3F1F9]",
                      fileView?.path === f.path && "bg-[#EFEDFB] font-bold")}>{f.path}</button>
                ))}
            </div>
            <div className="chat-scroll min-w-0 flex-1 overflow-auto rounded-xl border border-[#F0EDF6] bg-[#FDFCF9] p-3">
              {!fileView ? <div className="py-8 text-center text-[12px] text-muted">Pick a file — read-only. Your team edits these for you.</div> :
                fileView.binary ? <div className="py-8 text-center text-[12px] text-muted">Binary file — download it from Outputs.</div> :
                <pre className="whitespace-pre-wrap font-mono text-[11.5px] leading-relaxed text-ink-soft">{fileView.content}</pre>}
            </div>
          </div>
        ) : (
        <div className="chat-scroll flex-1 overflow-y-auto">
          {!data ? <div className="py-8 text-center text-muted">Loading…</div> :
            data.versions.length === 0 ? (
              <div className="py-8 text-center text-muted">No versions yet — they appear when your team ships file changes.</div>
            ) : data.versions.map((v, i) => (
              <div key={v.version_no} className="flex items-center gap-3 border-b border-[#F0EDF6] py-3 last:border-0">
                <span className="w-10 flex-none rounded-lg bg-[#EFEDF5] px-2 py-1 text-center font-mono text-[11px] font-bold text-secondary">v{v.version_no}</span>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-semibold">{v.label}</div>
                  <div className="text-[11px] text-muted">
                    {new Date(v.created_at).toLocaleString()} · {v.files} files
                    {data.repo_full_name && (v.pushed
                      ? <span className="ml-1 text-status-done">· synced {v.commit_sha ? v.commit_sha.slice(0, 7) : ""}</span>
                      : <span className="ml-1 text-status-needs-input">· sync pending</span>)}
                  </div>
                </div>
                {i !== 0 && (
                  <button onClick={() => restore(v.version_no)} disabled={busy !== null}
                    className="flex-none rounded-lg border border-[#E4DFEF] bg-white px-3 py-1 text-[12px] font-semibold text-primary-to hover:bg-[#F3F1F9] disabled:opacity-50">
                    {busy === v.version_no ? "Restoring…" : "Restore"}
                  </button>
                )}
              </div>
            ))}
        </div>
        )}
      </div>
    </Overlay>
  );
}
