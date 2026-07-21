"use client";

// GitHub App 설치 콜백(D61) — GitHub이 ?installation_id=로 리다이렉트하면 백엔드에 기록하고
// 워크스페이스로 복귀한다. (GitHub App 설정의 Setup URL = {SITE}/github/callback)
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import { apiFetch } from "@/lib/api";
import { pickProject } from "@/lib/lastProject";

export default function GithubCallback() {
  const router = useRouter();
  const { getToken, isLoaded, isSignedIn } = useAuth();
  const [msg, setMsg] = useState("Connecting your GitHub…");

  useEffect(() => {
    if (!isLoaded) return;
    if (!isSignedIn) { setMsg("Please sign in first, then reconnect from History."); return; }
    const params = new URLSearchParams(window.location.search);
    const id = params.get("installation_id");
    const code = params.get("code"); // OAuth during install — 개인 계정 리포 생성용 user 토큰 교환
    if (!id) { setMsg("Missing installation — try connecting again from History."); return; }
    (async () => {
      try {
        const token = await getToken();
        await apiFetch(`/api/github/install`, { method: "POST", token, body: JSON.stringify({ installation_id: Number(id), code }) });
        setMsg("GitHub connected ✓ Heading back to your office…");
        const projects = await apiFetch<{ id: string }[]>("/api/projects", { token });
        const target = pickProject(projects);
        setTimeout(() => router.replace(target ? `/app/${target}` : "/app"), 1200);
      } catch {
        setMsg("Connection failed — try again from the History panel.");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoaded, isSignedIn]);

  return (
    <main className="office-floor flex min-h-screen items-center justify-center text-ink">
      <div className="rounded-card border border-[#E4DFEF] bg-white px-10 py-8 text-center shadow-card">
        <div className="text-3xl">🐙</div>
        <div className="mt-3 text-lg font-bold">{msg}</div>
      </div>
    </main>
  );
}
