"use client";

// 온보딩 위저드(Flow 0) — calm gradient + grid, 680px 카드, 스테퍼.
// 5스텝: ① Google 사인인(앱 내 모달) ② 이름 ③ 프로젝트명 ④ 팀 멀티셀렉트(4) ⑤ 컨텍스트(선택).
// 로그인이 첫 스텝 — 사인인 전엔 다음 진행 불가(/app은 미들웨어가 별도 보호).
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { SignInButton, useAuth, useUser } from "@clerk/nextjs";
import { PillButton, Stepper } from "@/components/ui/primitives";
import { apiFetch, E2E, TEAM_TEMPLATES } from "@/lib/api";
import { pickProject, setLastProject } from "@/lib/lastProject";
import { CARPET } from "@/lib/tokens";

const STEPS = ["Sign in", "Your name", "Project", "Teams", "Context"];

/**
 * Onboarding — 처음 들어온 사용자를 위한 5단계 마법사. 끝나면 첫 프로젝트가 만들어진다.
 *
 * 무슨 일을 하나: ① Google 로그인 → ② 이름 → ③ 프로젝트명 → ④ 팀 고르기(복수) → ⑤ 컨텍스트(선택)
 *   순서로 받고, 마지막에 finish()가 POST /api/projects로 프로젝트+선택 팀들을 한 번에 생성한 뒤
 *   메인 맵 화면(/app/{id})으로 보낸다. 로그인 전엔 다음 단계로 못 넘어간다(첫 관문).
 * 누가 부르나: 랜딩의 '시작하기' 버튼 → /onboarding.
 * 연결: 생성 호출 → apiFetch (frontend/lib/api.ts) → create_project (backend/app/routers/projects.py).
 *   완료 후 이동 → frontend/app/app/[projectId]/page.tsx.
 */
export default function Onboarding() {
  const router = useRouter();
  const { isSignedIn, isLoaded, user } = useUser();
  const { getToken } = useAuth();
  const [step, setStep] = useState(0);
  const [displayName, setDisplayName] = useState("");
  const [projectName, setProjectName] = useState("");
  const [teams, setTeams] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 기존 프로젝트가 있는 로그인 사용자가 실수로 온보딩에 들어오면(랜딩/북마크 등) 새 프로젝트를
  // 또 만들지 않도록 워크스페이스로 되돌린다. 스위처의 "New project"만 ?new=1로 위저드를 강제한다.
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    document.title = "Get started · pondas.ai";
  }, []);

  useEffect(() => {
    if (!isLoaded) return; // Clerk 로딩 대기.
    const isNew = typeof window !== "undefined" && new URLSearchParams(window.location.search).get("new") === "1";
    if (E2E || !isSignedIn || isNew) { setChecking(false); return; } // 명시적 신규 생성/미로그인/E2E는 위저드 진행.
    let alive = true;
    (async () => {
      try {
        const token = await getToken();
        const projects = await apiFetch<{ id: string }[]>("/api/projects", { token });
        if (!alive) return;
        const target = pickProject(projects);
        if (target) { router.replace(`/app/${target}`); return; } // 이미 프로젝트가 있으면 워크스페이스로.
      } catch { /* 목록 조회 실패 시 그냥 위저드를 보여준다. */ }
      if (alive) setChecking(false);
    })();
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoaded, isSignedIn]);

  // 사인인되면 step 0(로그인)을 자동 통과(E2E 모드는 사인인 스킵).
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
          name: projectName || "My Project",
          template_keys: teams,
          display_name: displayName || user?.firstName || "Founder",
        }),
      });
      setLastProject(project.id); // 새 프로젝트를 마지막 방문지로 기록.
      router.push(`/app/${project.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create project");
      setBusy(false);
    }
  }

  // 로그인 사용자의 프로젝트 보유 여부를 확인하는 동안 위저드가 깜빡이지 않도록 로더를 보여준다.
  if (checking) {
    return (
      <main className="flex min-h-screen items-center justify-center font-nunito text-secondary" style={{ background: "#C6C9BC" }}>
        Loading…
      </main>
    );
  }

  return (
    <main
      className="relative flex min-h-screen items-center justify-center p-6 font-nunito text-ink"
      style={{
        background:
          "linear-gradient(160deg,#DDE4D6,#C6C9BC), repeating-linear-gradient(0deg,transparent,transparent 41px,rgba(90,95,80,0.05) 42px)",
      }}
    >
      <div className="absolute left-8 top-7 font-baloo text-2xl font-extrabold text-ink">pondas</div>

      <div className="w-full max-w-[680px] rounded-card border-[3px] border-white bg-floor p-9 shadow-card">
        <div className="mb-7 flex justify-center">
          <Stepper steps={STEPS} current={effectiveStep} />
        </div>

        {effectiveStep === 0 && (
          <Step title="Welcome to pondas" sub="Run a virtual company of AI agents.">
            <SignInButton mode="modal">
              <PillButton variant="primary">Sign in with Google</PillButton>
            </SignInButton>
          </Step>
        )}

        {effectiveStep === 1 && (
          <Step title="What should we call you?" sub="Your display name in the workspace.">
            <input
              autoFocus
              className="w-full max-w-sm rounded-pill border-2 border-white bg-white/70 px-5 py-3 text-center text-lg outline-none focus:border-primary-to"
              placeholder="Jane"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
            />
            <PillButton variant="primary" onClick={() => setStep(2)} disabled={!displayName.trim()}>
              Continue →
            </PillButton>
          </Step>
        )}

        {effectiveStep === 2 && (
          <Step title="Name your first project" sub="Each project is its own office map.">
            <input
              autoFocus
              className="w-full max-w-sm rounded-pill border-2 border-white bg-white/70 px-5 py-3 text-center text-lg outline-none focus:border-primary-to"
              placeholder="Acme Studio"
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
            />
            <PillButton variant="primary" onClick={() => setStep(3)} disabled={!projectName.trim()}>
              Continue →
            </PillButton>
          </Step>
        )}

        {effectiveStep === 3 && (
          <Step title="Pick your teams" sub="Each becomes an office room with its starting agent.">
            <div className="grid w-full grid-cols-2 gap-3">
              {TEAM_TEMPLATES.map((t) => {
                const sel = teams.includes(t.key);
                return (
                  <button
                    key={t.key}
                    onClick={() => toggleTeam(t.key)}
                    className="relative rounded-2xl border-[3px] p-4 text-left transition-all"
                    style={{
                      borderColor: sel ? "#3FB4DC" : "#fff",
                      background: sel ? CARPET[t.key] : "rgba(255,255,255,0.55)",
                    }}
                  >
                    {sel && (
                      <span className="absolute right-3 top-3 flex h-6 w-6 items-center justify-center rounded-full bg-primary-to font-baloo text-xs font-extrabold text-white">
                        ✓
                      </span>
                    )}
                    <div className="font-baloo text-lg font-extrabold">{t.name}</div>
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
          <Step title="Add context (optional)" sub="Drop files relevant to the project. You can also do this later.">
            <div className="flex w-full max-w-sm items-center justify-center rounded-2xl border-2 border-dashed border-muted-2 bg-white/40 px-6 py-10 text-sm text-secondary">
              Drag files here, or skip for now
            </div>
            {error && <div className="text-sm text-status-failed">{error}</div>}
            <PillButton variant="confirm" onClick={finish} disabled={busy}>
              {busy ? "Building…" : "Enter the office →"}
            </PillButton>
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
        <h1 className="font-baloo text-2xl font-extrabold">{title}</h1>
        <p className="mt-1 text-secondary">{sub}</p>
      </div>
      {children}
    </div>
  );
}
