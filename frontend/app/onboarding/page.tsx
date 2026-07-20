"use client";

// 온보딩 위저드 v2(Flow 0, D58/D59) — G-Clay 크롬, 사장님 프레이밍, 첫 목표 유도.
// 6스텝: ① Google 사인인 ② 이름 ③ 회사(프로젝트)명 ④ 팀 멀티셀렉트 ⑤ 컨텍스트(선택) ⑥ 첫 목표.
// ⑥이 마지막인 이유(D58): "뭘 시킬지"의 빈 캔버스가 최대 이탈 절벽 — 예시 목표를 고르면
// 오피스 진입 시 채팅에 프리필돼 첫 태스크까지 무중단으로 이어진다.
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { SignInButton, useAuth, useUser } from "@clerk/nextjs";
import { PillButton, Stepper } from "@/components/ui/primitives";
import { apiFetch, E2E, TEAM_TEMPLATES } from "@/lib/api";
import { pickProject, setLastProject } from "@/lib/lastProject";
import { CARPET } from "@/lib/tokens";

const STEPS = ["Sign in", "You", "Company", "Teams", "Context", "First goal"];

// 예시 첫 목표(D58) — 클릭 = 오케스트레이터 첫 메시지 프리필. 저작 카피, 팀 구성 무관하게 동작.
const EXAMPLE_GOALS = [
  { emoji: "🛍️", title: "An online store", goal: "Build an online store for handmade candles — landing page, product list, and a checkout page." },
  { emoji: "📱", title: "A habit tracker", goal: "Build a simple habit-tracking web app — daily checklist, streaks, and a progress page." },
  { emoji: "🔎", title: "Research first", goal: "Research my competitors in the meal-prep space and write a summary with a comparison table." },
];

/**
 * Onboarding — 처음 들어온 사용자를 위한 6단계 마법사. 끝나면 첫 회사(프로젝트)가 만들어진다.
 *
 * 무슨 일을 하나: ① Google 로그인 → ② 이름 → ③ 회사명 → ④ 팀 고르기 → ⑤ 컨텍스트(선택) → ⑥ 첫 목표
 *   순서로 받고, finish()가 POST /api/projects로 프로젝트+팀을 생성한 뒤 메인 맵으로 보낸다.
 *   ⑥에서 고른 목표는 ?goal=로 전달돼 오케스트레이터 챗 입력창에 프리필된다(Hud).
 * 누가 부르나: 랜딩의 'Start building' 버튼 → /onboarding.
 * 연결: 생성 호출 → apiFetch (frontend/lib/api.ts) → create_project (backend/app/routers/projects.py).
 */
export default function Onboarding() {
  const router = useRouter();
  const { isSignedIn, isLoaded, user } = useUser();
  const { getToken } = useAuth();
  const [step, setStep] = useState(0);
  const [displayName, setDisplayName] = useState("");
  const [projectName, setProjectName] = useState("");
  const [teams, setTeams] = useState<string[]>([]);
  const [files, setFiles] = useState<File[]>([]); // step 5에서 모은 컨텍스트 파일 — 프로젝트 생성 후 업로드.
  const [goal, setGoal] = useState("");           // step 6 — 첫 목표(선택). 오피스 챗에 프리필.
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 기존 프로젝트가 있는 로그인 사용자가 실수로 온보딩에 들어오면 워크스페이스로 되돌린다.
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    document.title = "Get started · pondas.ai";
  }, []);

  useEffect(() => {
    if (!isLoaded) return; // Clerk 로딩 대기.
    const isNew = typeof window !== "undefined" && new URLSearchParams(window.location.search).get("new") === "1";
    if (E2E || !isSignedIn || isNew) { setChecking(false); return; }
    let alive = true;
    (async () => {
      try {
        const token = await getToken();
        const projects = await apiFetch<{ id: string }[]>("/api/projects", { token });
        if (!alive) return;
        const target = pickProject(projects);
        if (target) { router.replace(`/app/${target}`); return; }
      } catch { /* 목록 조회 실패 시 그냥 위저드를 보여준다. */ }
      if (alive) setChecking(false);
    })();
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoaded, isSignedIn]);

  const effectiveStep = !(isSignedIn || E2E) ? 0 : Math.max(step, 1);

  function toggleTeam(key: string) {
    setTeams((t) => (t.includes(key) ? t.filter((k) => k !== key) : [...t, key]));
  }

  async function finish() {
    setBusy(true);
    setError(null);
    try {
      const token = E2E ? "e2e" : await getToken();
      const project = await apiFetch<{ id: string }>("/api/projects", {
        method: "POST",
        token,
        body: JSON.stringify({
          name: projectName || "My Company",
          template_keys: teams,
          display_name: displayName || user?.firstName || "Founder",
        }),
      });
      for (const f of files) {
        try {
          const fd = new FormData();
          fd.append("file", f);
          await apiFetch(`/api/projects/${project.id}/context`, { method: "POST", token, body: fd });
        } catch { /* 개별 파일 실패는 무시 — 컨텍스트는 선택 사항 */ }
      }
      setLastProject(project.id);
      // 첫 목표(D58) — 있으면 쿼리로 넘겨 챗 입력창에 프리필. Hud가 소비 후 URL에서 제거.
      const q = goal.trim() ? `?goal=${encodeURIComponent(goal.trim())}` : "";
      router.push(`/app/${project.id}${q}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create project");
      setBusy(false);
    }
  }

  if (checking) {
    return (
      <main className="office-floor flex min-h-screen items-center justify-center text-secondary">
        Loading…
      </main>
    );
  }

  const inputCls =
    "w-full max-w-sm rounded-[14px] border border-[#E4DFEF] bg-white px-5 py-3 text-center text-lg outline-none shadow-[0_4px_14px_rgba(110,100,168,0.12)] focus:border-primary-to";

  return (
    <main className="office-floor relative flex min-h-screen items-center justify-center p-6 text-ink">
      <div className="absolute left-8 top-7 text-2xl font-bold text-ink">pondas</div>

      <div className="w-full max-w-[680px] rounded-card border border-[#E4DFEF] bg-white p-9 shadow-card">
        <div className="mb-7 flex justify-center">
          <Stepper steps={STEPS} current={effectiveStep} />
        </div>

        {effectiveStep === 0 && (
          <Step title="Your AI company awaits" sub="Hire a team of AI employees. Tell them what to build. Watch them work.">
            <SignInButton mode="modal">
              <PillButton variant="primary">Sign in with Google</PillButton>
            </SignInButton>
          </Step>
        )}

        {effectiveStep === 1 && (
          <Step title="What should your team call you?" sub="You're the boss — this is the name your agents will report to.">
            <input autoFocus className={inputCls} placeholder="Jane"
              value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
            <PillButton variant="primary" onClick={() => setStep(2)} disabled={!displayName.trim()}>
              Continue →
            </PillButton>
          </Step>
        )}

        {effectiveStep === 2 && (
          <Step title="Name your company" sub="Each company gets its own office. You can run several.">
            <input autoFocus className={inputCls} placeholder="Acme Studio"
              value={projectName} onChange={(e) => setProjectName(e.target.value)} />
            <PillButton variant="primary" onClick={() => setStep(3)} disabled={!projectName.trim()}>
              Continue →
            </PillButton>
          </Step>
        )}

        {effectiveStep === 3 && (
          <Step title="Hire your teams" sub="Each team gets an office room and a starting employee. You can hire more later.">
            <div className="grid w-full grid-cols-2 gap-3">
              {TEAM_TEMPLATES.map((t) => {
                const sel = teams.includes(t.key);
                return (
                  <button
                    key={t.key}
                    onClick={() => toggleTeam(t.key)}
                    className="relative rounded-2xl border-2 p-4 text-left transition-all"
                    style={{
                      borderColor: sel ? "#7266D6" : "#E4DFEF",
                      background: sel ? CARPET[t.key] : "#FDFCF9",
                      boxShadow: sel ? "0 8px 20px rgba(114,102,214,0.2)" : "none",
                    }}
                  >
                    {sel && (
                      <span className="absolute right-3 top-3 flex h-6 w-6 items-center justify-center rounded-full bg-[#3AA45C] text-xs font-bold text-white">
                        ✓
                      </span>
                    )}
                    <div className="text-lg font-bold">{t.name}</div>
                    <div className="mt-1 text-xs text-secondary">{t.description}</div>
                    <div className="mt-2 font-mono text-[10px] text-muted">starts with {t.starter}</div>
                  </button>
                );
              })}
            </div>
            <PillButton variant="primary" onClick={() => setStep(4)} disabled={teams.length === 0}>
              Continue →
            </PillButton>
          </Step>
        )}

        {effectiveStep === 4 && (
          <Step title="Add context (optional)" sub="Files (txt, md, pdf · ≤ 10 MB) your team can read. You can also add these later in Settings.">
            <input
              ref={fileInputRef} type="file" accept=".txt,.md,.markdown,.pdf" multiple className="hidden"
              onChange={(e) => {
                const picked = Array.from(e.target.files ?? []);
                setFiles((prev) => [...prev, ...picked]);
                if (fileInputRef.current) fileInputRef.current.value = "";
              }}
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="flex w-full max-w-sm flex-col items-center justify-center rounded-2xl border-2 border-dashed border-[#C9C4DC] bg-[#FDFCF9] px-6 py-8 text-sm text-secondary transition-colors hover:border-primary-to hover:bg-white"
            >
              <span className="text-2xl">📎</span>
              <span className="mt-1">Click to choose files, or skip for now</span>
            </button>
            {files.length > 0 && (
              <div className="w-full max-w-sm space-y-1">
                {files.map((f, i) => (
                  <div key={`${f.name}-${i}`} className="flex items-center justify-between rounded-lg border border-[#E4DFEF] bg-white px-3 py-1.5 text-xs">
                    <span className="truncate font-bold">{f.name}</span>
                    <button type="button" onClick={() => setFiles((prev) => prev.filter((_, j) => j !== i))} className="shrink-0 text-status-failed hover:underline">Remove</button>
                  </div>
                ))}
              </div>
            )}
            <PillButton variant="primary" onClick={() => setStep(5)}>
              Continue →
            </PillButton>
          </Step>
        )}

        {effectiveStep === 5 && (
          <Step title="What should your team build first?" sub="Pick one to get going, write your own, or skip — you can always just talk to your team in the office.">
            <div className="grid w-full grid-cols-3 gap-3">
              {EXAMPLE_GOALS.map((g) => {
                const sel = goal === g.goal;
                return (
                  <button
                    key={g.title}
                    onClick={() => setGoal(sel ? "" : g.goal)}
                    className="rounded-2xl border-2 p-3 text-left transition-all"
                    style={{
                      borderColor: sel ? "#7266D6" : "#E4DFEF",
                      background: sel ? "#EFEDFB" : "#FDFCF9",
                      boxShadow: sel ? "0 8px 20px rgba(114,102,214,0.2)" : "none",
                    }}
                  >
                    <div className="text-xl">{g.emoji}</div>
                    <div className="mt-1 text-sm font-bold">{g.title}</div>
                    <div className="mt-1 text-[11px] leading-snug text-secondary">{g.goal}</div>
                  </button>
                );
              })}
            </div>
            <textarea
              className="w-full max-w-md rounded-[14px] border border-[#E4DFEF] bg-white px-4 py-3 text-sm outline-none shadow-[0_4px_14px_rgba(110,100,168,0.12)] focus:border-primary-to"
              rows={2}
              placeholder="…or describe your own first goal"
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
            />
            {error && <div className="text-sm text-status-failed">{error}</div>}
            <div className="flex items-center gap-3">
              <PillButton variant="confirm" onClick={finish} disabled={busy}>
                {busy ? "Building your office…" : "Enter your office →"}
              </PillButton>
              {!goal.trim() && (
                <button onClick={finish} disabled={busy} className="text-sm text-muted hover:underline">Skip</button>
              )}
            </div>
          </Step>
        )}
      </div>
    </main>
  );
}

function Step({ title, sub, children }: { title: string; sub: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-5 text-center">
      <div>
        <h1 className="text-2xl font-bold">{title}</h1>
        <p className="mt-1 text-secondary">{sub}</p>
      </div>
      {children}
    </div>
  );
}
