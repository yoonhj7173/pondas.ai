"use client";

// 시어터 모드(Phase 2, item 31, D51) — 오피스 위 오버레이로 돌아가는 앱을 크게 보고,
// 도킹된 오케스트레이터 챗으로 그 자리에서 수정 지시한다. 오피스=홈, 시어터=포커스.
import { useEffect, useRef, useState } from "react";
import clsx from "clsx";
import { apiFetch } from "@/lib/api";
import { useStore } from "@/lib/store";

interface VersionRow { version_no: number; agent_id: string | null; file_count: number; created_at: string }

/**
 * Theater — 프리뷰 오버레이. 열면 프리뷰를 기동(POST /preview/start)하고, 준비되면 iframe으로
 *   실제 앱을 크게 띄운다. 하단에 오케스트레이터 챗을 도킹해 "고쳐줘"를 그 자리에서 보낸다.
 * 누가 부르나: 오피스 페이지(app/[projectId]/page.tsx)가 store.theaterOpen일 때.
 * 연결: 프리뷰 상태는 store.preview(SSE preview_status로도 갱신). 챗 → onSend(=sendChat → POST /chat).
 */
export function Theater({ projectId, getToken, onSend, onClose }: {
  projectId: string; getToken: () => Promise<string | null>; onSend?: (m: string) => Promise<string | void>; onClose: () => void;
}) {
  const preview = useStore((s) => s.preview);
  const applyPreview = useStore((s) => s.applyPreview);
  const [versions, setVersions] = useState<VersionRow[]>([]);
  const [starting, setStarting] = useState(false);

  async function loadVersions() {
    try {
      const token = await getToken();
      setVersions(await apiFetch<VersionRow[]>(`/api/projects/${projectId}/versions`, { token }));
    } catch { /* 버전 없음/에러는 칩 없이 */ }
  }

  async function startPreview() {
    setStarting(true);
    try {
      const token = await getToken();
      const res = await apiFetch<{ status: string; url: string | null; version_no: number | null }>(
        `/api/projects/${projectId}/preview/start`, { method: "POST", token },
      );
      applyPreview(res.status, res.url, res.version_no);
    } catch {
      applyPreview("error", null, null);
    } finally {
      setStarting(false);
    }
  }

  // 열릴 때 프리뷰 기동 + 버전 로드. ESC로 닫기.
  useEffect(() => {
    startPreview();
    loadVersions();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const ready = preview.status === "ready" && preview.url;

  return (
    <div className="absolute inset-0 z-[60] flex flex-col gap-3 bg-[rgba(40,46,40,0.55)] p-5 backdrop-blur-sm md:p-6" role="dialog" aria-label="Live preview theater">
      {/* 상단 바 */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2 font-baloo text-sm font-extrabold text-white drop-shadow">
          <span className={clsx("inline-block h-2 w-2 rounded-full", ready ? "bg-green-300" : "bg-white/50")} />
          Live Preview
          <span className="rounded-pill border border-white/40 bg-white/15 px-2 py-0.5 text-[11px] font-bold text-white/90">
            {ready ? "running" : preview.status === "error" ? "failed to start" : preview.status === "none" ? "no runnable app" : "starting…"}
          </span>
        </div>
        <div className="flex-1" />
        {/* 버전 칩 */}
        <div className="flex items-center gap-1">
          {versions.slice(0, 5).reverse().map((v) => (
            <span key={v.version_no} className={clsx(
              "rounded-pill px-2.5 py-0.5 text-[11px] font-extrabold",
              v.version_no === preview.versionNo ? "bg-white text-ink" : "bg-white/15 text-white/70",
            )}>v{v.version_no}</span>
          ))}
        </div>
        <button onClick={onClose} className="btn-pill btn-danger !px-4 !py-2 text-xs">✕ Office</button>
      </div>

      {/* 브라우저 프레임 */}
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
        <div className="flex items-center gap-2 border-b border-[#dde2e9] bg-[#edf0f4] px-3 py-2">
          <div className="flex gap-1"><i className="h-2 w-2 rounded-full bg-[#ef7a66]" /><i className="h-2 w-2 rounded-full bg-[#f6c65b]" /><i className="h-2 w-2 rounded-full bg-[#74d982]" /></div>
          <div className="flex-1 truncate rounded-pill border border-[#dde2e9] bg-white px-3 py-1 font-mono text-[11px] text-[#4a5568]">
            {preview.url ?? "—"}
          </div>
          <button onClick={startPreview} className="rounded-pill border border-[#dde2e9] bg-white px-2.5 py-1 text-[11px] font-bold text-[#4a5568]" title="Reload">⟳</button>
          {preview.url && <a href={preview.url} target="_blank" rel="noreferrer" className="rounded-pill border border-[#dde2e9] bg-white px-2.5 py-1 text-[11px] font-bold text-[#2b6cb0]">↗ New tab</a>}
        </div>
        <div className="relative min-h-0 flex-1 bg-[#fbf6ee]">
          {ready ? (
            <iframe src={preview.url!} title="app preview" className="h-full w-full border-0" sandbox="allow-scripts allow-same-origin allow-forms" />
          ) : (
            <div className="flex h-full flex-col items-center justify-center gap-3 text-center text-ink-soft">
              {preview.status === "error" ? (
                <>
                  <div className="text-2xl">⚠️</div>
                  <div className="font-baloo text-lg font-extrabold">The app didn&apos;t start</div>
                  <p className="max-w-md text-sm text-muted">Ask the dev team to fix it in the chat below, then reload.</p>
                </>
              ) : preview.status === "none" ? (
                <>
                  <div className="text-2xl">📄</div>
                  <div className="font-baloo text-lg font-extrabold">No runnable app yet</div>
                  <p className="max-w-md text-sm text-muted">This project has no web app to preview. Ask the Development team to build one.</p>
                </>
              ) : (
                <>
                  <div className="h-8 w-8 animate-spin rounded-full border-[3px] border-primary-to/30 border-t-primary-to" />
                  <div className="font-baloo text-lg font-extrabold">Starting your app…</div>
                  <p className="text-sm text-muted">Installing and booting the dev server.</p>
                </>
              )}
            </div>
          )}
        </div>
      </div>

      {/* 도킹된 오케스트레이터 챗 */}
      <DockedChat onSend={onSend} disabled={starting} />
    </div>
  );
}

function DockedChat({ onSend, disabled }: { onSend?: (m: string) => Promise<string | void>; disabled?: boolean }) {
  const [msg, setMsg] = useState("");
  const [bubbles, setBubbles] = useState<{ role: "user" | "orchestrator"; text: string }[]>([]);
  const ref = useRef<HTMLInputElement>(null);

  async function send() {
    const m = msg.trim();
    if (!m) return;
    setBubbles((b) => [...b, { role: "user", text: m }]);
    setMsg("");
    const reply = await onSend?.(m);
    if (typeof reply === "string" && reply) setBubbles((b) => [...b, { role: "orchestrator", text: reply }]);
  }

  return (
    <div className="rounded-2xl border-2 border-white/80 bg-white/80 p-3 shadow-card backdrop-blur">
      {bubbles.length > 0 && (
        <div className="mb-2 max-h-28 space-y-1.5 overflow-y-auto">
          {bubbles.map((b, i) => (
            <div key={i} className={clsx("flex", b.role === "user" ? "justify-end" : "justify-start")}>
              <div className={clsx("max-w-[80%] rounded-2xl px-3 py-1.5 font-nunito text-[13px]", b.role === "user" ? "bg-primary-to text-white" : "bg-white text-ink shadow")}>
                {b.role === "orchestrator" && <span className="mr-1.5 font-baloo font-bold text-status-done">O</span>}{b.text}
              </div>
            </div>
          ))}
        </div>
      )}
      <div className="flex items-center gap-2 rounded-pill border-[2px] border-white bg-white px-2 py-1">
        <input ref={ref} value={msg} onChange={(e) => setMsg(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder="See it and ask for a change…" className="flex-1 bg-transparent px-3 py-1.5 font-nunito text-sm outline-none" />
        <button onClick={send} disabled={disabled} className="btn-pill btn-primary !px-4 !py-2 text-sm disabled:opacity-50">Send</button>
      </div>
    </div>
  );
}
