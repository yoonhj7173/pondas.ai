"use client";

// 프로젝트 오피스 맵 — 실 /map 엔드포인트 연결. HUD/패널은 item 23-25에서 얹는다.
import { useEffect, useState } from "react";
import { useAuth, UserButton } from "@clerk/nextjs";
import { apiFetch, E2E } from "@/lib/api";
import { useStore } from "@/lib/store";
import { connectSSE } from "@/lib/sse";
import type { MapData } from "@/lib/map/types";
import Hud from "@/components/hud/Hud";
import { PanelController, type Selection } from "@/components/panels/PanelController";
import { BoardOverlay, OutputsOverlay, SettingsOverlay, type OverlayKind } from "@/components/overlays/Overlays";
import { TreasuryTile, BillingModal } from "@/components/billing/Treasury";
import { Theater } from "@/components/preview/Theater";
import TeamCardOffice from "@/components/map/TeamCardOffice";

/**
 * ProjectMap — 제품의 메인 화면. 사무실 맵 + HUD(채팅·벨) + 패널/오버레이를 한 화면에 조립한다.
 *
 * 이 컴포넌트가 프론트의 중심 허브다. 백엔드에서 맵 데이터를 받아 그리고, 실시간 연결을 열고,
 * 사용자의 클릭(에이전트/팀 선택, 채팅 전송, 오버레이 열기)을 모두 여기서 받아 배분한다.
 *
 * 무슨 일을 하나:
 *   - loadMap: /map을 불러 사무실(팀·에이전트·연결선)을 그리고 store에 스냅샷 저장.
 *   - connectSSE: 실시간 연결을 열어 상태 변화를 화면에 반영.
 *   - sendChat: 채팅을 백엔드 지휘자에게 보냄(POST /chat).
 *   - openPanel/openOverlay: 패널(에이전트/팀)과 오버레이(보드/결과물/설정)를 상호배타로 토글.
 * 누가 부르나: Next.js 라우팅 — /app/{projectId} 접속 시.
 * 연결: 데이터 로드/전송 → frontend/lib/api.ts(→ 백엔드 projects.py/chat.py). 실시간 → frontend/lib/sse.ts.
 *   맵 렌더 → components/map/MapCanvas.tsx. 패널 → components/panels/PanelController.tsx.
 */
export default function ProjectMap({ params }: { params: { projectId: string } }) {
  const { getToken: clerkToken } = useAuth();
  const getToken = async () => (E2E ? "e2e" : await clerkToken());
  const [data, setData] = useState<MapData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sel, setSel] = useState<Selection>({ kind: "none" });
  const [overlay, setOverlay] = useState<OverlayKind>(null);
  const [billingOpen, setBillingOpen] = useState(false);
  const [billingPaywall, setBillingPaywall] = useState(false); // 소진으로 자동 오픈됐는지(배너 카피용).
  // 크레딧 부족으로 task가 막히면(SSE paywall 이벤트) 결제 모달 자동 노출(D46).
  const paywall = useStore((s) => s.paywall);
  const theaterOpen = useStore((s) => s.theaterOpen);
  useEffect(() => {
    if (paywall) {
      setBillingPaywall(true);
      setBillingOpen(true);
      useStore.getState().clearPaywall();
    }
  }, [paywall]);

  async function loadMap() {
    const token = await getToken();
    const map = await apiFetch<MapData>(`/api/projects/${params.projectId}/map`, { token });
    useStore.getState().setSnapshot(map);
    setData(map);
  }

  useEffect(() => {
    let disconnect: (() => void) | null = null;
    (async () => {
      try {
        await loadMap();
        const token = await getToken();
        if (token) disconnect = connectSSE(params.projectId, token); // 라이브 SSE
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load map");
      }
    })();
    return () => disconnect?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.projectId]);

  // 패널/모달 ↔ 오버레이 상호배타 — 하나 열면 다른 건 닫힌다.
  function openPanel(s: Selection) { setOverlay(null); setSel(s); }
  function openOverlay(o: OverlayKind) { setSel({ kind: "none" }); setOverlay(o); }
  function closeAll() { setSel({ kind: "none" }); setOverlay(null); }

  // Escape로 열린 패널/오버레이 닫기.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") closeAll(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // E2E QA 훅 — 캔버스 클릭 없이 패널/모달을 열 수 있게(테스트 전용).
  useEffect(() => {
    if (!E2E) return;
    (window as unknown as { __qa: unknown }).__qa = {
      selectAgent: (id: string) => openPanel({ kind: "agent", id }),
      selectTeam: (id: string) => openPanel({ kind: "team", id }),
      addAgent: (teamId: string) => openPanel({ kind: "addAgent", teamId }),
      addTeam: () => openPanel({ kind: "addTeam" }),
      openOverlay: (k: OverlayKind) => (k ? openOverlay(k) : closeAll()),
    };
  });

  async function sendChat(message: string): Promise<string | void> {
    try {
      const token = await getToken();
      const res = await apiFetch<{ reply: string }>(`/api/projects/${params.projectId}/chat`, {
        method: "POST", token, body: JSON.stringify({ message }),
      });
      return res.reply;
    } catch { /* HUD가 유저 버블만 보존 */ }
  }

  if (error) return <Centered>{error}</Centered>;
  if (!data) return <Centered>Loading office…</Centered>;

  return (
    <div className="relative h-screen w-screen overflow-hidden">
      <TeamCardOffice
        data={data}
        onSelectAgent={(id) => openPanel({ kind: "agent", id })}
        onSelectTeam={(id) => openPanel({ kind: "team", id })}
      />
      <Hud
        projectName={data.project.name}
        onSend={sendChat}
        onFocusAgent={(id) => openPanel({ kind: "agent", id })}
        onOpen={(w) => {
          if (w === "addTeam") openPanel({ kind: "addTeam" });
          else openOverlay(w);
        }}
      />
      {!E2E && (
        // 계정 메뉴(아바타 → 로그아웃). 좌하단 고정.
        <div className="absolute bottom-5 left-5 z-20 rounded-full bg-white/80 p-0.5 shadow-card">
          <UserButton afterSignOutUrl="/" />
        </div>
      )}
      {/* Treasury HUD 타일 + 충전 모달(빌링 D46). */}
      <TreasuryTile getToken={getToken} onOpen={() => { setBillingPaywall(false); setBillingOpen(true); }} />
      {billingOpen && <BillingModal getToken={getToken} paywall={billingPaywall} onClose={() => { setBillingOpen(false); setBillingPaywall(false); }} />}
      <PanelController projectId={params.projectId} getToken={getToken} mapData={data} sel={sel} setSel={setSel} onChanged={loadMap} onOpenOutputs={() => openOverlay("outputs")} onOpenTheater={() => useStore.getState().setTheater(true)} />
      {theaterOpen && <Theater projectId={params.projectId} getToken={getToken} onSend={sendChat} onClose={() => useStore.getState().setTheater(false)} />}
      {overlay === "board" && <BoardOverlay projectId={params.projectId} getToken={getToken} onClose={() => setOverlay(null)} onFocus={(id) => { setOverlay(null); setSel({ kind: "agent", id }); }} />}
      {overlay === "outputs" && <OutputsOverlay projectId={params.projectId} getToken={getToken} onClose={() => setOverlay(null)} />}
      {overlay === "settings" && <SettingsOverlay projectId={params.projectId} getToken={getToken} projectName={data.project.name} paused={data.paused} onClose={() => setOverlay(null)} onChanged={loadMap} />}
    </div>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <main className="flex min-h-screen items-center justify-center font-nunito text-secondary" style={{ background: "#C6C9BC" }}>
      {children}
    </main>
  );
}
