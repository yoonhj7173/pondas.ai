"use client";

// 프로젝트 오피스 맵 — 실 /map 엔드포인트 연결. HUD/패널은 item 23-25에서 얹는다.
import { useEffect, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import dynamic from "next/dynamic";
import { apiFetch, E2E } from "@/lib/api";
import { useStore } from "@/lib/store";
import { connectSSE } from "@/lib/sse";
import type { MapData } from "@/lib/map/types";
import Hud from "@/components/hud/Hud";
import { PanelController, type Selection } from "@/components/panels/PanelController";
import { BoardOverlay, OutputsOverlay, SettingsOverlay, type OverlayKind } from "@/components/overlays/Overlays";

const MapCanvas = dynamic(() => import("@/components/map/MapCanvas"), { ssr: false });

export default function ProjectMap({ params }: { params: { projectId: string } }) {
  const { getToken: clerkToken } = useAuth();
  const getToken = async () => (E2E ? "e2e" : await clerkToken());
  const [data, setData] = useState<MapData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sel, setSel] = useState<Selection>({ kind: "none" });
  const [overlay, setOverlay] = useState<OverlayKind>(null);

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

  async function persistRoom(teamId: string, x: number, y: number) {
    const token = await getToken();
    await apiFetch(`/api/teams/${teamId}`, { method: "PATCH", token, body: JSON.stringify({ room_x: x, room_y: y }) }).catch(() => {});
  }

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
      <MapCanvas
        data={data}
        callbacks={{
          onRoomMoved: persistRoom,
          onSelectAgent: (id) => setSel({ kind: "agent", id }),
          onSelectTeam: (id) => setSel({ kind: "team", id }),
          onDeselect: () => setSel({ kind: "none" }),
        }}
      />
      <Hud
        projectName={data.project.name}
        onSend={sendChat}
        onFocusAgent={(id) => setSel({ kind: "agent", id })}
        onOpen={(w) => {
          if (w === "addTeam") setSel({ kind: "addTeam" });
          else setOverlay(w);
        }}
      />
      <PanelController projectId={params.projectId} getToken={getToken} mapData={data} sel={sel} setSel={setSel} onChanged={loadMap} />
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
