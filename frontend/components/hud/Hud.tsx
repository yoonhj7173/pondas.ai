"use client";

// 맵 위 HUD 레이어(item 23) — 오케스트레이터 챗 · Activity 피드 · 벨/드로어 · 토스트 ·
// 토큰 카운터 · 프로젝트 스위처 · 유틸 버튼. 전부 store에서 파생(D36).
import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import dynamic from "next/dynamic";
import { useAuth } from "@clerk/nextjs";
import clsx from "clsx";
import { useStore, type FeedEvent, type NotifRow } from "@/lib/store";
import { STATUS_CHIP, visualStatus } from "@/lib/tokens";
import { apiFetch, E2E } from "@/lib/api";
import { ding } from "@/lib/sound";
import { enablePush, pushGranted, pushSupported } from "@/lib/push";

// 채팅 말풍선 마크다운(QA-03-2) — office 기본 청크를 가볍게 유지(lazy, Markdown.tsx 컨벤션).
const Markdown = dynamic(() => import("@/components/ui/Markdown"), { ssr: false });

export interface HudProps {
  projectName: string;
  onSend?: (msg: string) => Promise<string | void> | string | void;
  onFocusAgent?: (agentId: string) => void;
  onOpen?: (what: "settings" | "board" | "outputs" | "notes" | "history" | "addTeam") => void;
  currentProjectId?: string;
  treasurySlot?: React.ReactNode; // 크레딧 타일 — 우하단 토큰 카운터 옆에 나란히 배치(위치는 HUD가 잡음).
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
      <UnifiedActivity onFocusAgent={props.onFocusAgent} projectId={props.currentProjectId} />
      <ToastStack onFocusAgent={props.onFocusAgent} />
      <UtilityStack onOpen={props.onOpen} />
      {/* 우하단: 크레딧 타일 + 토큰 카운터를 세로로 그룹핑(2-2). 가로 배치는 가운데 챗바와 겹쳐 세로 스택.
          토큰이 위(팝오버가 위로 열려 빈 공간 사용), 크레딧이 아래. */}
      <div className="absolute bottom-5 right-5 z-20 flex flex-col items-end gap-2">
        <TokenCounter projectId={props.currentProjectId} />
        {props.treasurySlot}
      </div>
      <OrchestratorChat focused={chatFocused} setFocused={setChatFocused} onSend={props.onSend} projectId={props.currentProjectId} />
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
            onClick={() => { setOpen(false); router.push("/onboarding?new=1"); }}
            className="flex w-full items-center gap-2 border-t border-[#eeefe7] px-3 py-2.5 text-sm font-extrabold text-[#2f9fc7] hover:bg-black/5"
          >
            <span className="text-base leading-none">＋</span> New project
          </button>
        </div>
      )}
    </div>
  );
}

// --- 통합 Activity(top-right, QA-04) — 영속 알림(DB) + 라이브 피드를 한 타임라인으로 ---
//
// 병합 규칙: 종결 이벤트(done/failed/needs-input/blocked)는 영속 notifications가 담당(새로고침
// 후에도 남고 읽음 상태 있음), 휘발 이벤트(working 시작/채팅 답변)는 라이브 피드가 담당.
// 라이브 피드의 종결 행은 걸러서 같은 사건이 두 번 보이지 않게 한다. 별도 벨 버튼은 제거 —
// 미읽음 칩과 읽음 처리가 패널 헤더로 들어왔다(어차피 벨 드로어 UI는 존재한 적이 없었다).
type TimelineRow =
  | { kind: "live"; key: string; ts: number; e: FeedEvent }
  | { kind: "notif"; key: string; ts: number; n: NotifRow };

function UnifiedActivity({ onFocusAgent, projectId }: { onFocusAgent?: (id: string) => void; projectId?: string }) {
  const { getToken: clerkToken } = useAuth();
  const events = useStore((s) => s.events);
  const notifs = useStore((s) => s.notifs);
  const unread = useStore((s) => s.unread);
  const connected = useStore((s) => s.connected);
  const progress = useStore((s) => s.progress);
  const agents = useStore((s) => s.agents);
  const [expanded, setExpanded] = useState(false);
  // Web Push(D56⑤) — 아직 권한 없으면 활성 버튼 노출. 서버 미설정(config.enabled=false)이면 숨김.
  const [pushState, setPushState] = useState<"unknown" | "off" | "on" | "unavailable">("unknown");
  useEffect(() => {
    if (!pushSupported()) { setPushState("unavailable"); return; }
    if (pushGranted()) { setPushState("on"); return; }
    (async () => {
      try {
        const token = await clerkToken();
        const cfg = await apiFetch<{ enabled: boolean }>("/api/push/config", { token });
        setPushState(cfg.enabled ? "off" : "unavailable");
      } catch { setPushState("unavailable"); }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  async function onEnablePush() {
    try {
      const ok = await enablePush(await clerkToken());
      if (ok) setPushState("on");
    } catch { /* 권한 거부 등 — 버튼 유지 */ }
  }
  const scrollRef = useRef<HTMLDivElement>(null);
  const stick = useRef(true); // 사용자가 위로 스크롤하지 않았으면 최신으로 자동 스크롤 유지.

  // 영속 알림 로드(QA-04) — 프로젝트 스코프. 새로고침해도 종결 히스토리가 남는 근원.
  useEffect(() => {
    if (!projectId) return;
    let alive = true;
    (async () => {
      try {
        const token = E2E ? "e2e" : await clerkToken();
        const rows = await apiFetch<{ id: string; agent_id: string | null; type: string; message: string; read: boolean; created_at: string }[]>(
          `/api/notifications?project_id=${projectId}`, { token });
        if (!alive) return;
        useStore.getState().setNotifications(rows.map((r) => ({
          id: r.id, agentId: r.agent_id, type: r.type, message: r.message, read: r.read,
          ts: new Date(r.created_at).getTime(),
        })));
      } catch { /* 영속 히스토리는 부가 — 라이브 피드는 계속 동작 */ }
    })();
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  async function markAllRead() {
    useStore.getState().markAllRead(); // 낙관적 — 뱃지/하이라이트 즉시 제거.
    try {
      const token = E2E ? "e2e" : await clerkToken();
      await apiFetch(`/api/notifications/read-all`, { method: "POST", token });
    } catch { /* 서버 실패 시 다음 로드에서 unread로 복원됨 */ }
  }

  // 타임라인 병합: 종결=notifs, 휘발(working/queued 시작 + 채팅)=live. 시간 오름차순(아래=최신).
  const live: TimelineRow[] = events
    .filter((e) => e.kind === "chat" || ["working", "queued"].includes(visualStatus(e.status as any)))
    .map((e) => ({ kind: "live" as const, key: `e${e.id}`, ts: e.ts, e }));
  const persisted: TimelineRow[] = notifs.map((n) => ({ kind: "notif" as const, key: `n${n.id}`, ts: n.ts, n }));
  const rows = [...persisted, ...live].sort((a, b) => a.ts - b.ts).slice(expanded ? -80 : -30);

  useEffect(() => {
    const el = scrollRef.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [events, notifs, expanded, progress]);
  const onScroll = () => {
    const el = scrollRef.current;
    if (el) stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24; // 바닥 근처면 계속 붙어서 스크롤.
  };

  // 라이브 진행 서브라인(QA-01)은 "그 에이전트의 가장 최근 working 행"에만 붙인다.
  const latestWorkingRow: Record<string, string> = {};
  for (const r of rows) {
    if (r.kind === "live" && r.e.kind !== "chat") latestWorkingRow[r.e.agentId] = r.key;
  }

  return (
    <div className="absolute right-5 top-5 z-20">
      <div className={clsx("rounded-tile border border-[#E4DFEF] bg-white/95 p-3 text-ink shadow-panel transition-[width] duration-200", expanded ? "w-[400px]" : "w-[312px]")}>
        <div className="mb-2 flex items-center justify-between">
          <span className="flex items-center gap-2">
            <span className="font-baloo text-sm font-bold">Activity</span>
            {unread > 0 && (
              <button onClick={markAllRead} title="Mark all read"
                className="flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-status-failed px-1.5 text-[10px] font-bold hover:opacity-85">
                {unread}
              </button>
            )}
          </span>
          <span className="flex items-center gap-2">
            <span className="flex items-center gap-1 font-mono text-[10px]"><span className={clsx("h-1.5 w-1.5 rounded-full", connected ? "bg-status-done" : "bg-muted")} />LIVE</span>
            {unread > 0 && <button onClick={markAllRead} title="Mark all read" className="text-[12px] leading-none opacity-70 hover:opacity-100">✓ read</button>}
            <button onClick={() => setExpanded((e) => !e)} title={expanded ? "Collapse" : "Expand"} className="px-1 text-[15px] leading-none opacity-70 hover:opacity-100">{expanded ? "⤡" : "⤢"}</button>
          </span>
        </div>
        {pushState === "off" && (
          <button onClick={onEnablePush}
            className="mb-2 w-full rounded-lg border border-dashed border-[#C9C4DC] px-2 py-1.5 text-[11px] font-semibold text-secondary hover:bg-[#F3F1F9]">
            🔔 Get notified on your phone when agents need you
          </button>
        )}
        <div ref={scrollRef} onScroll={onScroll} className={clsx("chat-scroll overflow-y-auto transition-[max-height] duration-200", expanded ? "max-h-[62vh]" : "max-h-[40vh]")}>
          {rows.length === 0 && <div className="py-2 text-xs opacity-40">No activity yet</div>}
          {rows.map((r) =>
            r.kind === "notif" ? (
              <NotifRowView key={r.key} n={r.n} onClick={() => r.n.agentId && onFocusAgent?.(r.n.agentId)} />
            ) : (
              <FeedRow
                key={r.key}
                e={r.e}
                // 진행 중 행에만 라이브 진행 한 줄(에이전트가 아직 working일 때).
                progressLabel={
                  latestWorkingRow[r.e.agentId] === r.key && ["working", "queued"].includes(agents[r.e.agentId]?.status ?? "")
                    ? progress[r.e.agentId]?.label
                    : undefined
                }
                onClick={() => r.e.agentId && onFocusAgent?.(r.e.agentId)}
              />
            ),
          )}
        </div>
      </div>
    </div>
  );
}

// 이벤트 → 타입 아이콘(QA-06): 시작/완료/실패/입력대기/채팅이 한눈에 구분되게.
const NOTIF_ICON: Record<string, { glyph: string; bg: string }> = {
  done: { glyph: "✓", bg: "#4dbb5c" },
  failed: { glyph: "✕", bg: "#e8503a" },
  "needs-input": { glyph: "!", bg: "#efb43e" },
  blocked: { glyph: "⏸", bg: "#efb43e" },
};

function feedIcon(e: FeedEvent): { glyph: string; bg: string } {
  if (e.kind === "chat") return { glyph: "💬", bg: "rgba(255,255,255,.12)" };
  const v = visualStatus(e.status as any);
  if (v === "working" || v === "queued") return { glyph: "▶", bg: "#3fb4dc" };
  return NOTIF_ICON[v] ?? { glyph: "·", bg: "rgba(255,255,255,.18)" };
}

// 영속 알림 행(QA-04) — 서버 메시지("PM finished" 등) + 미읽음 하이라이트.
function NotifRowView({ n, onClick }: { n: NotifRow; onClick: () => void }) {
  const icon = NOTIF_ICON[n.type] ?? { glyph: "·", bg: "rgba(255,255,255,.18)" };
  return (
    <button onClick={onClick} className={clsx("flex w-full items-start gap-2 rounded-lg px-1.5 py-1.5 text-left font-nunito text-[11px] hover:bg-[#F3F1F9]", !n.read && "bg-[#F3F1F9]")}>
      <span className="mt-px flex h-[18px] w-[18px] flex-none items-center justify-center rounded-full text-[9px] font-bold text-white" style={{ background: icon.bg }}>{icon.glyph}</span>
      <span className="min-w-0 flex-1 break-words">
        {n.message}
        {!n.read && <span className="ml-1.5 inline-block h-1.5 w-1.5 rounded-full bg-status-working align-middle" />}
      </span>
      <span className="mt-px shrink-0 font-mono text-[9px] opacity-40">{time(n.ts)}</span>
    </button>
  );
}

function FeedRow({ e, progressLabel, onClick }: { e: FeedEvent; progressLabel?: string; onClick: () => void }) {
  const v = visualStatus(e.status as any);
  const icon = feedIcon(e);
  return (
    <button onClick={onClick} className="flex w-full items-start gap-2 rounded-lg px-1.5 py-1.5 text-left font-nunito text-[11px] hover:bg-[#F3F1F9]">
      <span className="mt-px flex h-[18px] w-[18px] flex-none items-center justify-center rounded-full text-[9px] font-bold text-white" style={{ background: icon.bg }}>{icon.glyph}</span>
      <span className="min-w-0 flex-1">
        {/* wrap 허용(QA-06) — crop 대신 전체 내용이 보이게. */}
        <span className="break-words">
          <b>{e.agent}</b>{e.team && <span className="opacity-50"> · {e.team}</span>}{" "}
          <span style={{ color: e.kind === "chat" ? "#9fd6ea" : chipFg(v) }}>{e.kind === "chat" ? "replied" : e.status}</span>
        </span>
        {e.detail && <span className="mt-0.5 block break-words text-[10.5px] opacity-60">{e.detail}</span>}
        {progressLabel && (
          <span className="mt-0.5 block truncate font-mono text-[10px] text-[#8fd4ef]">✏️ {progressLabel}</span>
        )}
      </span>
      <span className="mt-px shrink-0 font-mono text-[9px] opacity-40">{time(e.ts)}</span>
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
function UtilityStack({ onOpen }: { onOpen?: (w: "settings" | "board" | "outputs" | "notes" | "history" | "addTeam") => void }) {
  return (
    <div className="absolute bottom-5 left-5 z-20 flex flex-col gap-2">
      <Util onClick={() => onOpen?.("settings")}>⚙ Settings</Util>
      <Util onClick={() => onOpen?.("board")}>▦ Board</Util>
      <Util onClick={() => onOpen?.("notes")}>📝 Notes</Util>
      <Util onClick={() => onOpen?.("outputs")}>📄 Outputs</Util>
      <Util onClick={() => onOpen?.("history")}>🕘 History</Util>
      <Util variant="confirm" onClick={() => onOpen?.("addTeam")}>+ Team</Util>
    </div>
  );
}
function Util({ children, onClick, variant = "primary" }: { children: React.ReactNode; onClick?: () => void; variant?: "primary" | "confirm" }) {
  return <button onClick={onClick} className={clsx("btn-pill text-[13px]", variant === "confirm" ? "btn-confirm" : "btn-primary")}>{children}</button>;
}

// --- 토큰 카운터(bottom-right) + 상세 팝오버 ---
interface UsageBucket { id: string; name: string; tokens_in: number; tokens_out: number; cost_usd: number }
interface UsageData {
  total_tokens_in: number; total_tokens_out: number; total_cost_usd: number;
  today_tokens_in: number; today_tokens_out: number;
  by_team: UsageBucket[]; by_agent: UsageBucket[];
}

function TokenCounter({ projectId }: { projectId?: string }) {
  const usage = useStore((s) => s.usage); // 세션 누적(SSE tick) — 버튼의 라이브 숫자.
  const total = usage.tokensIn + usage.tokensOut;
  const { getToken: clerkToken } = useAuth();
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<UsageData | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  // 팝오버 열 때마다 서버 usage를 새로고침(권위 있는 집계 — today/total/by-team).
  useEffect(() => {
    if (!open || !projectId) return;
    let alive = true;
    (async () => {
      try {
        const token = E2E ? "e2e" : await clerkToken();
        const u = await apiFetch<UsageData>(`/api/projects/${projectId}/usage`, { token });
        if (alive) setData(u);
      } catch { /* 조용히 무시 — 버튼은 세션 숫자로 계속 동작 */ }
    })();
    return () => { alive = false; };
  }, [open, projectId, clerkToken]);

  // 바깥 클릭/ESC로 닫기.
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => { if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onKey); };
  }, [open]);

  const today = data ? data.today_tokens_in + data.today_tokens_out : null;
  const projTotal = data ? data.total_tokens_in + data.total_tokens_out : null;
  const teams = data ? [...data.by_team].sort((a, b) => (b.tokens_in + b.tokens_out) - (a.tokens_in + a.tokens_out)) : [];

  return (
    <div ref={wrapRef} className="relative">
      {open && (
        <div className="absolute bottom-full right-0 mb-2 w-64 rounded-tile border border-[#E4DFEF] bg-white p-3 text-ink shadow-card">
          <div className="mb-2 font-baloo text-sm font-bold">Token usage</div>
          <TokRow label="Today" value={today} />
          <TokRow label="Total (this project)" value={projTotal} />
          <div className="mb-1 mt-2 font-mono text-[10px] uppercase tracking-wide opacity-50">By team</div>
          {teams.length === 0 && <div className="py-0.5 text-xs opacity-40">{data ? "No usage yet" : "Loading…"}</div>}
          {teams.map((t) => <TokRow key={t.id} label={t.name} value={t.tokens_in + t.tokens_out} small />)}
        </div>
      )}
      <button
        onClick={() => setOpen((o) => !o)}
        title="Token usage details"
        className="flex items-center gap-2 rounded-tile border border-[#E4DFEF] bg-white/95 px-4 py-2.5 text-ink shadow-panel hover:bg-white"
      >
        <span className="font-baloo text-base font-bold">🪙 {total.toLocaleString()}</span>
        <span className="font-mono text-[10px] opacity-60">tokens {open ? "▾" : "▴"}</span>
      </button>
    </div>
  );
}

function TokRow({ label, value, small }: { label: string; value: number | null; small?: boolean }) {
  return (
    <div className={clsx("flex items-center justify-between gap-2 py-0.5", small ? "text-[11px]" : "text-xs")}>
      <span className="truncate opacity-70">{label}</span>
      <span className="shrink-0 font-mono font-bold">{value == null ? "—" : value.toLocaleString()}</span>
    </div>
  );
}

// --- 오케스트레이터 챗(bottom-center) ---
/**
 * OrchestratorChat — 회사를 지휘하는 채팅창(QA-03 오버홀).
 *
 * 무슨 일을 하나: ① 열면 저장된 대화 히스토리를 로드해 이어 보여주고(GET /chat/history),
 *   ② 입력을 받아 사용자 말풍선을 먼저 띄우고(낙관적), ③ 응답 대기 중엔 typing 인디케이터,
 *   ④ 지휘자 답변은 마크다운으로 렌더, ⑤ 항상 최신 메시지에 붙고 위로 스크롤하면 ↓ 버튼,
 *   ⑥ 입력은 멀티라인(Enter 전송 / Shift+Enter 줄바꿈), ⑦ 채팅이 닫혀 있을 때 답이 오면
 *   Activity/벨로 알린다(pushChatEvent).
 * 누가 부르나: Hud. 연결: onSend → ProjectMap.sendChat → POST /chat → run_chat (backend/app/services/orchestrator.py).
 */
function OrchestratorChat({ focused, setFocused, onSend, projectId }: {
  focused: boolean; setFocused: (f: boolean) => void; onSend?: HudProps["onSend"]; projectId?: string;
}) {
  const { getToken: clerkToken } = useAuth();
  const [msg, setMsg] = useState("");
  // 첫 목표 프리필(D58) — 온보딩 ⑥에서 ?goal=로 넘어온 목표를 입력창에 채우고 챗을 연다.
  // 소비 후 URL에서 제거(새로고침/공유 시 재프리필 방지). 디스패치는 유저의 Send 클릭에 맡긴다.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const goal = params.get("goal");
    if (!goal) return;
    setMsg(goal);
    setFocused(true);
    params.delete("goal");
    const q = params.toString();
    window.history.replaceState(null, "", window.location.pathname + (q ? `?${q}` : ""));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const [bubbles, setBubbles] = useState<{ role: "user" | "orchestrator" | "event"; text: string }[]>([]);
  // 태스크 종결 라이브 이벤트 라인(B1) — SSE가 store에 쌓으면 여기서 소비해 버블로 append.
  const chatEvents = useStore((s) => s.chatEvents);
  const consumedEvents = useRef(0);
  const [sending, setSending] = useState(false); // 디스패치 중 — Enter/클릭 연타로 중복 디스패치 차단.
  const [atBottom, setAtBottom] = useState(true);
  const ref = useRef<HTMLTextAreaElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const focusedRef = useRef(focused); // 응답 도착 시점의 열림 여부 판단(비동기 콜백에서 최신값 필요).
  focusedRef.current = focused;

  // 저장된 대화 히스토리 로드(QA-03-1) — 프로젝트당 1회. 열기 전에 미리 받아 열자마자 보이게.
  useEffect(() => {
    if (!projectId) return;
    let alive = true;
    (async () => {
      try {
        const token = E2E ? "e2e" : await clerkToken();
        const rows = await apiFetch<{ role: string; content: string }[]>(`/api/projects/${projectId}/chat/history`, { token });
        if (alive && rows.length) {
          setBubbles(rows.map((r) => ({
            role: r.role === "orchestrator" ? "orchestrator" as const
              : r.role === "event" ? "event" as const : "user" as const,
            // 이벤트 행은 "[event] " 프리픽스 제거하고 회색 라인으로(B1).
            text: r.role === "event" ? r.content.replace(/^\[event\]\s*/, "") : r.content,
          })));
        }
      } catch { /* 히스토리는 부가 정보 — 실패해도 채팅은 동작 */ }
    })();
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  // 라이브 이벤트 라인 소비(B1) — store에 새로 쌓인 것만 버블로 append(중복 방지 카운터).
  useEffect(() => {
    if (chatEvents.length > consumedEvents.current) {
      const fresh = chatEvents.slice(consumedEvents.current);
      consumedEvents.current = chatEvents.length;
      setBubbles((b) => [...b, ...fresh.map((e) => ({ role: "event" as const, text: e.text }))]);
    }
  }, [chatEvents]);

  function scrollToBottom(smooth = false) {
    const el = scrollRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" });
  }
  // 열림 전환 시 무조건 최신으로 — 컨테이너가 갓 마운트되면 scrollHeight가 아직 안 잡혀서
  // 동기 스크롤은 맨 위(top=0)에 머문다. rAF로 레이아웃 후 바닥으로 붙이고 stick 상태를 리셋.
  useEffect(() => {
    if (!focused) return;
    setAtBottom(true);
    const id = requestAnimationFrame(() => scrollToBottom());
    return () => cancelAnimationFrame(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focused]);
  // 새 말풍선/typing 때 최신으로(QA-03-7). 사용자가 위로 스크롤한 상태면 붙지 않고 ↓ 버튼.
  useEffect(() => {
    if (focused && atBottom) scrollToBottom();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bubbles, sending]);
  const onScroll = () => {
    const el = scrollRef.current;
    if (el) setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 32);
  };

  async function send() {
    const m = msg.trim();
    if (!m || sending) return;
    setSending(true);
    setBubbles((b) => [...b, { role: "user", text: m }]);
    setMsg("");
    setAtBottom(true);
    if (ref.current) ref.current.style.height = "auto"; // textarea 높이 리셋
    try {
      const reply = await onSend?.(m);
      if (typeof reply === "string" && reply) {
        setBubbles((b) => [...b, { role: "orchestrator", text: reply }]);
        // 채팅을 닫아둔 채 답이 도착 → Activity/벨로 알림 + 소리(QA-06/04).
        if (!focusedRef.current) { useStore.getState().pushChatEvent(reply); ding("chat"); }
      }
    } finally {
      setSending(false);
    }
  }

  // textarea 자동 성장(최대 ~5줄).
  function autoGrow() {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
  }

  return (
    <div className="absolute bottom-5 left-1/2 z-30 w-[640px] max-w-[90vw] -translate-x-1/2">
      {focused && (bubbles.length > 0 || sending) && (
        <div className="relative">
          <div
            ref={scrollRef}
            onScroll={onScroll}
            onMouseDown={(e) => e.preventDefault()} // 메시지 영역 클릭이 입력 blur(=창 닫힘)로 이어지지 않게.
            className="chat-scroll mb-3 space-y-2 overflow-y-auto pr-1"
            style={{ maxHeight: "calc(100vh - 220px)" }} // 세로 풀높이(QA-03-5) — 상단 HUD/하단 입력만 남기고 다 쓴다.
          >
            {bubbles.map((b, i) => (
              b.role === "event" ? (
                // 태스크 종결 이벤트 라인(B1) — 말풍선이 아닌 중앙 회색 시스템 라인.
                <div key={i} className="flex justify-center">
                  <div className="rounded-full bg-black/5 px-3 py-1 font-nunito text-xs text-secondary">
                    {b.text}
                  </div>
                </div>
              ) : (
              <div key={i} className={clsx("flex", b.role === "user" ? "justify-end" : "justify-start")}>
                <div className={clsx("max-w-[80%] rounded-2xl px-4 py-2 font-nunito text-sm shadow", b.role === "user" ? "bg-primary-to text-white whitespace-pre-wrap" : "bg-white text-ink")}>
                  {b.role === "orchestrator"
                    ? <Markdown className="prose-chat">{b.text}</Markdown>  // 마크다운 렌더(QA-03-2)
                    : b.text}
                </div>
              </div>
              )
            ))}
            {sending && ( // typing 인디케이터(QA-03-3)
              <div className="flex justify-start">
                <div className="flex items-center gap-1.5 rounded-2xl bg-white px-4 py-3 shadow">
                  <span className="typing-dot" /><span className="typing-dot" style={{ animationDelay: "0.18s" }} /><span className="typing-dot" style={{ animationDelay: "0.36s" }} />
                </div>
              </div>
            )}
          </div>
          {!atBottom && ( // scroll-to-bottom(QA-03-7)
            <button
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => { setAtBottom(true); scrollToBottom(true); }}
              className="absolute bottom-4 right-3 flex h-9 w-9 items-center justify-center rounded-full border border-black/5 bg-white text-base text-secondary shadow-card"
              title="Jump to latest"
            >↓</button>
          )}
        </div>
      )}
      <div className="flex items-end gap-2 rounded-[24px] border-[2.5px] border-white bg-white/90 px-2 py-1.5 shadow-card">
        <textarea
          ref={ref}
          rows={1}
          value={msg}
          onChange={(e) => { setMsg(e.target.value); autoGrow(); }}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          onKeyDown={(e) => {
            // Enter 전송 / Shift+Enter 줄바꿈(QA-03-4). IME 조합 중 Enter는 무시(한글 입력 보호).
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(); }
            if (e.key === "Escape") (e.target as HTMLTextAreaElement).blur();
          }}
          placeholder="Tell your team what to do…  (Shift+Enter for a new line)"
          className="chat-scroll max-h-[120px] flex-1 resize-none bg-transparent px-3 py-2 font-nunito text-sm outline-none"
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
