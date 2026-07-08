"use client";

// 맵 위 HUD 레이어(item 23) — 오케스트레이터 챗 · Activity 피드 · 벨/드로어 · 토스트 ·
// 토큰 카운터 · 프로젝트 스위처 · 유틸 버튼. 전부 store에서 파생(D36).
import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import clsx from "clsx";
import { useStore, type FeedEvent } from "@/lib/store";
import { STATUS_CHIP, visualStatus } from "@/lib/tokens";
import { apiFetch, E2E } from "@/lib/api";

export interface HudProps {
  projectName: string;
  onSend?: (msg: string) => Promise<string | void> | string | void;
  onFocusAgent?: (agentId: string) => void;
  onOpen?: (what: "settings" | "board" | "outputs" | "addTeam") => void;
  currentProjectId?: string;
}

/**
 * Hud — 맵 위에 떠 있는 조작 레이어. 채팅창·알림벨·활동피드·토스트·토큰카운터·유틸버튼을 모은다.
 *
 * 무슨 일을 하나: 게임의 HUD처럼 맵 위에 겹쳐지는 UI를 한 묶음으로 배치한다. 표시 내용은 거의 전부
 *   store에서 파생된다(실시간 갱신). 핵심은 하단 중앙의 OrchestratorChat — 여기서 사용자가 회사를 지휘한다.
 * 누가 부르나: 메인 맵 화면 — frontend/app/app/[projectId]/page.tsx.
 * 연결: 상태 소스 → frontend/lib/store.ts. 채팅 전송 → 부모의 onSend → 백엔드 chat.py.
 *   (내부 하위 컴포넌트: ProjectSwitcher/ActivityFeedAndBell/ToastStack/UtilityStack/TokenCounter/OrchestratorChat)
 */
export default function Hud(props: HudProps) {
  const [chatFocused, setChatFocused] = useState(false);
  return (
    <>
      {/* 챗 포커스 시 월드 디밍. */}
      {chatFocused && <div className="pointer-events-none absolute inset-0 z-10 bg-[rgba(40,46,40,0.28)]" />}
      <ProjectSwitcher name={props.projectName} currentProjectId={props.currentProjectId} />
      <ActivityFeedAndBell onFocusAgent={props.onFocusAgent} />
      <ToastStack onFocusAgent={props.onFocusAgent} />
      <UtilityStack onOpen={props.onOpen} />
      <TokenCounter />
      <OrchestratorChat focused={chatFocused} setFocused={setChatFocused} onSend={props.onSend} />
    </>
  );
}

// --- 프로젝트 스위처(top-left) — 목록/전환/생성/삭제 드롭다운 ---
function ProjectSwitcher({ name, currentProjectId }: { name: string; currentProjectId?: string }) {
  const router = useRouter();
  const { getToken: clerkToken } = useAuth();
  const getToken = async () => (E2E ? "e2e" : await clerkToken());

  const [open, setOpen] = useState(false);
  const [projects, setProjects] = useState<{ id: string; name: string }[]>([]);
  const [loading, setLoading] = useState(false);
  const [confirmId, setConfirmId] = useState<string | null>(null); // 삭제 확인 중인 행
  const wrapRef = useRef<HTMLDivElement>(null);

  // 열 때마다 목록 새로고침(생성/삭제 후 최신 반영).
  useEffect(() => {
    if (!open) { setConfirmId(null); return; }
    let alive = true;
    (async () => {
      setLoading(true);
      try {
        const token = await getToken();
        const rows = await apiFetch<{ id: string; name: string }[]>("/api/projects", { token });
        if (alive) setProjects(rows);
      } catch {
        if (alive) setProjects([]);
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // 바깥 클릭/ESC로 닫기.
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onKey); };
  }, [open]);

  function goTo(id: string) {
    setOpen(false);
    if (id !== currentProjectId) router.push(`/app/${id}`);
  }

  const [delErr, setDelErr] = useState<string | null>(null);

  async function del(id: string) {
    setDelErr(null);
    try {
      const token = await getToken();
      await apiFetch(`/api/projects/${id}`, { method: "DELETE", token });
    } catch (e) {
      // 삭제 실패 → 목록/이동 그대로 두고 에러 표시(거짓 성공 금지). 유저가 재시도 가능.
      setDelErr(e instanceof Error ? e.message : "Couldn't delete — try again");
      return;
    }
    const rest = projects.filter((p) => p.id !== id);
    setProjects(rest);
    setConfirmId(null);
    // 현재 보고 있는 프로젝트를 지웠으면 → 다른 프로젝트 or 온보딩으로.
    if (id === currentProjectId) router.push(rest.length ? `/app/${rest[0].id}` : "/onboarding");
  }

  return (
    <div ref={wrapRef} className="absolute left-5 top-5 z-30">
      <button
        onClick={() => setOpen((o) => !o)}
        className="btn-pill btn-primary max-w-[220px] text-sm"
        title="Switch, create, or delete projects"
      >
        <span className="truncate">{name}</span> <span className="opacity-80">▾</span>
      </button>

      {open && (
        <div className="mt-2 w-[264px] overflow-hidden rounded-tile border border-[#e6e7dd] bg-white/97 shadow-card backdrop-blur">
          <div className="border-b border-[#eeefe7] px-3 py-2 text-[11px] font-bold uppercase tracking-wide text-[#a9a89c]">
            Your projects
          </div>
          <div className="max-h-[320px] overflow-y-auto py-1">
            {loading ? (
              <div className="px-3 py-2.5 text-sm text-[#8f8c7e]">Loading…</div>
            ) : projects.length === 0 ? (
              <div className="px-3 py-2.5 text-sm text-[#8f8c7e]">No projects yet</div>
            ) : (
              projects.map((p) => {
                const current = p.id === currentProjectId;
                return (
                  <div key={p.id} className="group flex items-center">
                    {confirmId === p.id ? (
                      <div className="w-full px-3 py-2 text-sm">
                        <div className="flex items-center justify-between gap-2">
                          <span className="truncate text-[#c0341f]">Delete “{p.name}”?</span>
                          <span className="flex flex-none gap-2">
                            <button onClick={() => del(p.id)} className="font-extrabold text-[#e8503a] hover:underline">Delete</button>
                            <button onClick={() => { setConfirmId(null); setDelErr(null); }} className="text-[#8f8c7e] hover:underline">Cancel</button>
                          </span>
                        </div>
                        {delErr && <div className="mt-1 text-[11px] text-[#c0341f]">{delErr}</div>}
                      </div>
                    ) : (
                      <>
                        <button
                          onClick={() => goTo(p.id)}
                          className="flex min-w-0 flex-1 items-center gap-2 px-3 py-2 text-left text-sm hover:bg-black/5"
                        >
                          <span className={clsx("truncate", current ? "font-extrabold text-[#2c2925]" : "text-[#55514a]")}>{p.name}</span>
                          {current && <span className="flex-none text-[#4dbb5c]">✓</span>}
                        </button>
                        <button
                          onClick={() => setConfirmId(p.id)}
                          title="Delete project"
                          className="flex-none px-2.5 py-2 text-[#b7b6ab] opacity-0 transition group-hover:opacity-100 hover:text-[#e8503a]"
                        >
                          🗑
                        </button>
                      </>
                    )}
                  </div>
                );
              })
            )}
          </div>
          <button
            onClick={() => { setOpen(false); router.push("/onboarding"); }}
            className="flex w-full items-center gap-2 border-t border-[#eeefe7] px-3 py-2.5 text-sm font-extrabold text-[#2f9fc7] hover:bg-black/5"
          >
            <span className="text-base leading-none">＋</span> New project
          </button>
        </div>
      )}
    </div>
  );
}

// --- Activity 피드 + 벨(top-right) ---
function ActivityFeedAndBell({ onFocusAgent }: { onFocusAgent?: (id: string) => void }) {
  const events = useStore((s) => s.events);
  const unread = useStore((s) => s.unread);
  const connected = useStore((s) => s.connected);
  const markAllRead = useStore((s) => s.markAllRead);
  const [drawerOpen, setDrawerOpen] = useState(false);

  return (
    <div className="absolute right-5 top-5 z-20 flex items-start gap-2">
      <button
        onClick={() => { setDrawerOpen((o) => !o); markAllRead(); }}
        className="relative flex h-11 w-11 items-center justify-center rounded-tile bg-[rgba(36,46,66,0.92)] text-lg text-white"
      >
        🔔
        {unread > 0 && <span className="absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-status-failed px-1 text-[10px] font-bold">{unread}</span>}
      </button>
      <div className="w-[296px] rounded-tile bg-[rgba(36,46,66,0.92)] p-3 text-white">
        <div className="mb-2 flex items-center justify-between">
          <span className="font-baloo text-sm font-bold">Activity</span>
          <span className="flex items-center gap-1 font-mono text-[10px]"><span className={clsx("h-1.5 w-1.5 rounded-full", connected ? "bg-status-done" : "bg-muted")} />LIVE</span>
        </div>
        <div className="max-h-[40vh] overflow-y-auto">
          {events.length === 0 && <div className="py-2 text-xs opacity-40">No activity yet</div>}
          {events.slice(0, 30).map((e) => (
            <FeedRow key={e.id} e={e} onClick={() => onFocusAgent?.(e.agentId)} />
          ))}
        </div>
      </div>
    </div>
  );
}

function FeedRow({ e, onClick }: { e: FeedEvent; onClick: () => void }) {
  const v = visualStatus(e.status as any);
  const tinted = v === "failed" || v === "needs-input";
  return (
    <button onClick={onClick} className={clsx("flex w-full items-center justify-between gap-2 rounded px-1.5 py-1 text-left font-nunito text-[11px] hover:bg-white/5", tinted && "bg-white/[0.06]")}>
      <span className="truncate">
        <span className="opacity-50">[{e.team}]</span> {e.agent} <span style={{ color: chipFg(v) }}>{e.status}</span>
      </span>
      <span className="shrink-0 font-mono text-[9px] opacity-40">{time(e.ts)}</span>
    </button>
  );
}

// --- 토스트(top-center) — terminal/needs-input 이벤트. ---
function ToastStack({ onFocusAgent }: { onFocusAgent?: (id: string) => void }) {
  const events = useStore((s) => s.events);
  const [dismissed, setDismissed] = useState<Set<number>>(new Set());
  const toasts = events.filter((e) => ["needs-input", "failed", "done"].includes(visualStatus(e.status as any)) && !dismissed.has(e.id)).slice(0, 3);
  return (
    <div className="pointer-events-none absolute left-1/2 top-5 z-30 flex -translate-x-1/2 flex-col items-center gap-2">
      {toasts.map((e) => (
        <div key={e.id} className="pointer-events-auto flex items-center gap-3 rounded-pill border-[2.5px] border-white bg-floor px-4 py-2 shadow-card">
          <span className="flex h-6 w-6 items-center justify-center rounded-full text-white text-xs" style={{ background: chipFg(visualStatus(e.status as any)) }}>!</span>
          <span className="font-nunito text-sm"><b>{e.agent}</b> ({e.team}) {e.status}</span>
          <button onClick={() => onFocusAgent?.(e.agentId)} className="btn-pill btn-primary !px-3 !py-1 text-xs">View</button>
          <button onClick={() => setDismissed((s) => new Set(s).add(e.id))} className="text-muted">×</button>
        </div>
      ))}
    </div>
  );
}

// --- 유틸 버튼(bottom-left) ---
function UtilityStack({ onOpen }: { onOpen?: (w: "settings" | "board" | "outputs" | "addTeam") => void }) {
  return (
    <div className="absolute bottom-5 left-5 z-20 flex flex-col gap-2">
      <Util onClick={() => onOpen?.("settings")}>⚙ Settings</Util>
      <Util onClick={() => onOpen?.("board")}>▦ Board</Util>
      <Util onClick={() => onOpen?.("outputs")}>📄 Outputs</Util>
      <Util variant="confirm" onClick={() => onOpen?.("addTeam")}>+ Team</Util>
    </div>
  );
}
function Util({ children, onClick, variant = "primary" }: { children: React.ReactNode; onClick?: () => void; variant?: "primary" | "confirm" }) {
  return <button onClick={onClick} className={clsx("btn-pill text-[13px]", variant === "confirm" ? "btn-confirm" : "btn-primary")}>{children}</button>;
}

// --- 토큰 카운터(bottom-right) ---
function TokenCounter() {
  const usage = useStore((s) => s.usage);
  const total = usage.tokensIn + usage.tokensOut;
  return (
    <div className="absolute bottom-5 right-5 z-20 rounded-tile bg-[rgba(36,46,66,0.92)] px-4 py-2 text-white">
      <div className="font-baloo text-sm font-bold">🪙 {total.toLocaleString()}</div>
      <div className="font-mono text-[10px] opacity-70">TOKENS TODAY</div>
    </div>
  );
}

// --- 오케스트레이터 챗(bottom-center) ---
/**
 * OrchestratorChat — 회사를 지휘하는 채팅창. 사용자가 한 줄 쓰면 지휘자에게 보내고 답을 말풍선으로 띄운다.
 *
 * 무슨 일을 하나: 입력을 받아 사용자 말풍선을 먼저 띄우고(낙관적 업데이트 — 서버 답 전에 화면 먼저 반영),
 *   onSend로 백엔드에 보내 지휘자 답변이 오면 답 말풍선을 추가한다.
 * 누가 부르나: Hud. 연결: onSend → ProjectMap.sendChat → POST /chat → run_chat (backend/app/services/orchestrator.py).
 */
function OrchestratorChat({ focused, setFocused, onSend }: { focused: boolean; setFocused: (f: boolean) => void; onSend?: HudProps["onSend"] }) {
  const [msg, setMsg] = useState("");
  const [bubbles, setBubbles] = useState<{ role: "user" | "orchestrator"; text: string }[]>([]);
  const [sending, setSending] = useState(false); // 디스패치 중 — Enter/클릭 연타로 중복 디스패치 차단.
  const ref = useRef<HTMLInputElement>(null);

  async function send() {
    const m = msg.trim();
    if (!m || sending) return;
    setSending(true);
    setBubbles((b) => [...b, { role: "user", text: m }]);
    setMsg("");
    try {
      const reply = await onSend?.(m);
      if (typeof reply === "string" && reply) setBubbles((b) => [...b, { role: "orchestrator", text: reply }]);
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="absolute bottom-5 left-1/2 z-30 w-[640px] max-w-[90vw] -translate-x-1/2">
      {focused && bubbles.length > 0 && (
        <div className="mb-3 max-h-[40vh] space-y-2 overflow-y-auto">
          {bubbles.map((b, i) => (
            <div key={i} className={clsx("flex", b.role === "user" ? "justify-end" : "justify-start")}>
              <div className={clsx("max-w-[80%] rounded-2xl px-4 py-2 font-nunito text-sm shadow", b.role === "user" ? "bg-primary-to text-white" : "bg-white text-ink")}>
                {b.role === "orchestrator" && <span className="mr-2 font-baloo font-bold">O</span>}
                {b.text}
              </div>
            </div>
          ))}
        </div>
      )}
      <div className="flex items-center gap-2 rounded-pill border-[2.5px] border-white bg-white/90 px-2 py-1 shadow-card">
        <input
          ref={ref}
          value={msg}
          onChange={(e) => setMsg(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder="Tell your team what to do…"
          className="flex-1 bg-transparent px-3 py-2 font-nunito text-sm outline-none"
        />
        <button onMouseDown={(e) => e.preventDefault()} onClick={send} disabled={sending} className="btn-pill btn-primary !px-4 !py-2 text-sm disabled:opacity-60">Send</button>
      </div>
    </div>
  );
}

function chipFg(v: string): string {
  return (STATUS_CHIP[v] ?? STATUS_CHIP.idle).fg;
}
function time(ts: number): string {
  return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
