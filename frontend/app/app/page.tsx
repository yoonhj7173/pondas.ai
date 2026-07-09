"use client";

// /app 인덱스 — bare /app 진입 시 갈 곳을 정한다(전에는 이 라우트가 없어 404).
// 로그인 유저의 최신 프로젝트로 보내고, 프로젝트가 없으면 온보딩으로. (미인증은 미들웨어가 이미 온보딩으로 차단.)
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import { apiFetch, E2E } from "@/lib/api";
import { pickProject } from "@/lib/lastProject";

export default function AppIndex() {
  const router = useRouter();
  const { getToken: clerkToken } = useAuth();

  useEffect(() => {
    document.title = "Loading… · pondas.ai";
    let alive = true;
    (async () => {
      try {
        const token = E2E ? "e2e" : await clerkToken();
        const projects = await apiFetch<{ id: string }[]>("/api/projects", { token });
        if (!alive) return;
        // 마지막으로 연 프로젝트로 복귀(없거나 삭제됐으면 최신). 프로젝트가 하나도 없으면 온보딩.
        const target = pickProject(projects);
        router.replace(target ? `/app/${target}` : "/onboarding");
      } catch {
        if (alive) router.replace("/onboarding");
      }
    })();
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <main className="flex min-h-screen items-center justify-center font-nunito text-secondary" style={{ background: "#C6C9BC" }}>
      Loading your office…
    </main>
  );
}
