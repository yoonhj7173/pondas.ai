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
  // 디자인 코멘트 모드(item 39, D56④) — 이 페르소나의 개입 모국어는 diff가 아니라 "여기 이거".
  // 크로스오리진 iframe이라 셀렉터 캡처 대신 좌표(% + 뷰포트)를 구조화해 디스패치한다(P1: 주입 스크립트).
  const [commentMode, setCommentMode] = useState(false);
  const [pin, setPin] = useState<{ x: number; y: number; w: number; h: number } | null>(null);
  const [pinText, setPinText] = useState("");
  const [pinSent, setPinSent] = useState(false);

  function onOverlayClick(e: React.MouseEvent<HTMLDivElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    setPin({
      x: Math.round(((e.clientX - rect.left) / rect.width) * 100),
      y: Math.round(((e.clientY - rect.top) / rect.height) * 100),
      w: Math.round(rect.width), h: Math.round(rect.height),
    });
    setPinText(""); setPinSent(false);
  }

  async function sendPin() {
    if (!pin || !pinText.trim()) return;
    const msg = `[Design comment] On preview v${preview.versionNo ?? "?"}, I clicked at (${pin.x}%, ${pin.y}%) of a ${pin.w}×${pin.h} viewport and want this change: "${pinText.trim()}". Identify the UI element at that location and apply the change.`;
    setPinSent(true);
    await onSend?.(msg);
    setTimeout(() => { setPin(null); setCommentMode(false); }, 900);
  }

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

  // iteration(D51): 새 버전이 커팅되면(SSE preview_status version_no↑) 칩 목록을 다시 불러온다.
  // iframe은 key=versionNo로 remount돼 변경이 바로 보인다(HMR 보강용 하드 리로드).
  useEffect(() => {
    if (preview.versionNo != null) loadVersions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preview.versionNo]);

  const ready = preview.status === "ready" && preview.url;
  const disabled = preview.status === "disabled";

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
          <button onClick={() => { setCommentMode((m) => !m); setPin(null); }}
            className={clsx("rounded-pill border px-2.5 py-1 text-[11px] font-bold",
              commentMode ? "border-primary-to bg-primary-to text-white" : "border-[#dde2e9] bg-white text-[#4a5568]")}
            title="Click an element in the preview and describe the change">💬 Point &amp; comment</button>
          <button onClick={startPreview} className="rounded-pill border border-[#dde2e9] bg-white px-2.5 py-1 text-[11px] font-bold text-[#4a5568]" title="Reload">⟳</button>
          {preview.url && <a href={preview.url} target="_blank" rel="noreferrer" className="rounded-pill border border-[#dde2e9] bg-white px-2.5 py-1 text-[11px] font-bold text-[#2b6cb0]">↗ New tab</a>}
        </div>
        <div className="relative min-h-0 flex-1 bg-[#fbf6ee]">
          {ready ? (
            <>
              <iframe key={preview.versionNo ?? "v"} src={preview.url!} title="app preview" className="h-full w-full border-0" sandbox="allow-scripts allow-same-origin allow-forms" />
              {commentMode && (
                <div onClick={onOverlayClick} className="absolute inset-0 cursor-crosshair bg-primary-to/5"
                  title="Click where you want a change">
                  {!pin && (
                    <div className="pointer-events-none absolute left-1/2 top-4 -translate-x-1/2 rounded-pill bg-[rgba(24,22,36,0.85)] px-4 py-1.5 text-[12px] font-semibold text-white">
                      Click the spot you want changed
                    </div>
                  )}
                </div>
              )}
              {commentMode && pin && (
                <div className="absolute z-10" style={{ left: `${pin.x}%`, top: `${pin.y}%` }} onClick={(e) => e.stopPropagation()}>
                  <div className="-ml-2 -mt-2 h-4 w-4 rounded-full border-2 border-white bg-primary-to shadow" />
                  <div className="mt-1 w-64 -translate-x-1/2 rounded-xl border border-[#E4DFEF] bg-white p-2 shadow-card">
                    {pinSent ? (
                      <div className="py-1 text-center text-[13px] font-semibold text-status-done">Sent to the team ✓</div>
                    ) : (
                      <>
                        <input autoFocus value={pinText} onChange={(e) => setPinText(e.target.value)}
                          onKeyDown={(e) => e.key === "Enter" && sendPin()}
                          placeholder='e.g. "make this button green"'
                          className="w-full rounded-lg border border-[#E4DFEF] px-2 py-1.5 text-[13px] outline-none focus:border-primary-to" />
                        <div className="mt-1.5 flex justify-end gap-2">
                          <button onClick={() => setPin(null)} className="text-[11px] text-muted hover:underline">Cancel</button>
                          <button onClick={sendPin} disabled={!pinText.trim()}
                            className="rounded-lg bg-primary-to px-3 py-1 text-[12px] font-bold text-white disabled:opacity-50">Send</button>
                        </div>
                      </>
                    )}
                  </div>
                </div>
              )}
            </>
          ) : (
            <div className="flex h-full flex-col items-center justify-center gap-3 text-center text-ink-soft">
              {disabled ? (
                <>
                  <div className="text-2xl">🔒</div>
                  <div className="font-baloo text-lg font-extrabold">Live preview is coming soon</div>
                  <p className="max-w-md text-sm text-muted">Preview isn&apos;t enabled on your workspace yet. Your files are safe — download them from Outputs anytime.</p>
                </>
              ) : preview.status === "error" ? (
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
      <DockedChat onSend={onSend} disabled={starting} versionNo={ready ? preview.versionNo : null} />
    </div>
  );
}

function DockedChat({ onSend, disabled, versionNo }: { onSend?: (m: string) => Promise<string | void>; disabled?: boolean; versionNo?: number | null }) {
  const [msg, setMsg] = useState("");
  const [bubbles, setBubbles] = useState<{ role: "user" | "orchestrator"; text: string }[]>([]);
  const ref = useRef<HTMLInputElement>(null);
  const seenVersion = useRef<number | null>(null);

  // 프리뷰가 새 버전으로 갱신되면(iteration 완료) 시스템 확인 버블을 남긴다.
  useEffect(() => {
    if (versionNo == null) return;
    if (seenVersion.current != null && versionNo > seenVersion.current) {
      setBubbles((b) => [...b, { role: "orchestrator", text: `Applied — preview updated ✓ v${versionNo}` }]);
    }
    seenVersion.current = versionNo;
  }, [versionNo]);

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
