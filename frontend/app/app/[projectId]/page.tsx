"use client";

// 프로젝트 오피스 맵 — 실 /map 엔드포인트 연결. HUD/패널은 item 23-25에서 얹는다.
import { useEffect, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import dynamic from "next/dynamic";
import { apiFetch } from "@/lib/api";
import type { MapData } from "@/lib/map/types";

const MapCanvas = dynamic(() => import("@/components/map/MapCanvas"), { ssr: false });

export default function ProjectMap({ params }: { params: { projectId: string } }) {
  const { getToken } = useAuth();
  const [data, setData] = useState<MapData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const token = await getToken();
        setData(await apiFetch<MapData>(`/api/projects/${params.projectId}/map`, { token }));
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load map");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.projectId]);

  async function persistRoom(teamId: string, x: number, y: number) {
    const token = await getToken();
    await apiFetch(`/api/teams/${teamId}`, { method: "PATCH", token, body: JSON.stringify({ room_x: x, room_y: y }) }).catch(() => {});
  }

  if (error) return <Centered>{error}</Centered>;
  if (!data) return <Centered>Loading office…</Centered>;

  return (
    <div className="h-screen w-screen">
      <MapCanvas
        data={data}
        callbacks={{
          onRoomMoved: persistRoom,
          onSelectAgent: (id) => console.log("agent", id), // 패널은 item 24
          onSelectTeam: (id) => console.log("team", id),
        }}
      />
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
