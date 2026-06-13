"use client";

// 온보딩 위저드(Flow 0) — calm gradient + grid, 680px 카드, 스테퍼.
// 5스텝: ① Google 사인인 ② 이름 ③ 프로젝트명 ④ 팀 멀티셀렉트(4) ⑤ 컨텍스트(선택).
import { useState } from "react";
import { useRouter } from "next/navigation";
import { SignInButton, useAuth, useUser } from "@clerk/nextjs";
import { PillButton, Stepper } from "@/components/ui/primitives";
import { apiFetch, E2E, TEAM_TEMPLATES } from "@/lib/api";
import { CARPET } from "@/lib/tokens";

const STEPS = ["Sign in", "Your name", "Project", "Teams", "Context"];

export default function Onboarding() {
  const router = useRouter();
  const { isSignedIn, user } = useUser();
  const { getToken } = useAuth();
  const [step, setStep] = useState(0);
  const [displayName, setDisplayName] = useState("");
  const [projectName, setProjectName] = useState("");
  const [teams, setTeams] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 사인인되면 step 0을 자동 통과(E2E 모드는 사인인 스킵).
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
      router.push(`/app/${project.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create project");
      setBusy(false);
    }
  }

  return (
    <main
      className="relative flex min-h-screen items-center justify-center p-6 font-nunito text-ink"
      style={{
        background:
          "linear-gradient(160deg,#DDE4D6,#C6C9BC), repeating-linear-gradient(0deg,transparent,transparent 41px,rgba(90,95,80,0.05) 42px)",
      }}
    >
      <div className="absolute left-8 top-7 font-baloo text-2xl font-extrabold text-ink">Craft</div>

      <div className="w-full max-w-[680px] rounded-card border-[3px] border-white bg-floor p-9 shadow-card">
        <div className="mb-7 flex justify-center">
          <Stepper steps={STEPS} current={effectiveStep} />
        </div>

        {effectiveStep === 0 && (
          <Step title="Welcome to Craft" sub="Run a virtual company of AI agents.">
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
