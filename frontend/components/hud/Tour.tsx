"use client";

// 첫 진입 투어(QA-06) — 실유저 4/5가 프로젝트만 만들고 태스크 0으로 이탈("이제 뭘 하지?").
// 3스텝 카드로 오피스/오케스트레이터/에이전트를 설명하고 첫 채팅으로 유도한다.
// localStorage 1회 표시(스킵 가능). 재보기는 추후 설정에서.
import { useEffect, useState } from "react";

const TOUR_KEY = "pondas_tour_v1";

const STEPS = [
  {
    emoji: "🏢",
    title: "This is your AI office",
    body: "Each card is a team of AI agents — your product managers, designers, and engineers. They do real work and hand results to each other.",
  },
  {
    emoji: "💬",
    title: "The Orchestrator is your manager",
    body: "Tell it what you want to build in the chat below. It breaks your idea into tasks and dispatches the right agents — you never assign work by hand.",
  },
  {
    emoji: "⚡",
    title: "Watch the work happen",
    body: "Agents light up while they work — live progress shows in the Activity feed (top right) and on each agent. Click any agent to see details, outputs, or stop a task.",
  },
];

export function shouldShowTour(): boolean {
  try { return !localStorage.getItem(TOUR_KEY); } catch { return false; }
}

export default function Tour({ onDone }: { onDone: () => void }) {
  const [step, setStep] = useState(0);

  function finish() {
    try { localStorage.setItem(TOUR_KEY, "done"); } catch { /* private mode 등 — 그냥 진행 */ }
    onDone();
  }

  // ESC = 스킵.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") finish(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const s = STEPS[step];
  const last = step === STEPS.length - 1;

  return (
    <div className="absolute inset-0 z-40 flex items-center justify-center bg-[rgba(40,46,40,0.45)]">
      <div className="w-[400px] max-w-[88vw] rounded-card border-[3px] border-white bg-floor p-6 shadow-card">
        <div className="font-mono text-[10px] font-bold uppercase tracking-widest text-primary-to">
          {step + 1} / {STEPS.length}
        </div>
        <div className="mt-2 flex items-start gap-3">
          <span className="grid h-12 w-12 flex-none place-items-center rounded-2xl bg-white text-2xl shadow-[0_4px_10px_rgba(50,55,45,.12)]">{s.emoji}</span>
          <div>
            <h3 className="font-baloo text-lg font-extrabold text-ink">{s.title}</h3>
            <p className="mt-1 text-sm leading-relaxed text-secondary">{s.body}</p>
          </div>
        </div>
        <div className="mt-5 flex items-center justify-between">
          <span className="flex items-center gap-1.5">
            {STEPS.map((_, i) => (
              <span key={i} className={`h-1.5 w-1.5 rounded-full ${i === step ? "bg-primary-to" : "bg-[#d8dacd]"}`} />
            ))}
          </span>
          <span className="flex items-center gap-3">
            {!last && <button onClick={finish} className="text-sm font-bold text-muted hover:text-secondary">Skip</button>}
            <button
              onClick={() => (last ? finish() : setStep(step + 1))}
              className="btn-pill btn-primary !px-5 !py-2 text-sm"
            >
              {last ? "Start building" : "Next"}
            </button>
          </span>
        </div>
      </div>
    </div>
  );
}
