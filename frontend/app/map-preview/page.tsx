"use client";

// 맵 비주얼 프리뷰(개발용) — 목 데이터로 Pixi 월드 검증. 인증/백엔드 불필요.
import dynamic from "next/dynamic";
import type { MapData } from "@/lib/map/types";

const MapCanvas = dynamic(() => import("@/components/map/MapCanvas"), { ssr: false });

const MOCK: MapData = {
  project: { id: "preview", name: "Acme Studio", paused: false },
  paused: false,
  teams: [
    {
      id: "t1", name: "Development", template_key: "development", engine: "agent_sdk",
      room_x: 40, room_y: 40,
      agents: [
        { id: "a1", name: "SWE", model_tier: "strong", slot: 0, status: "working" },
        { id: "a2", name: "QA", model_tier: "medium", slot: 1, status: "needs-input" },
        { id: "a3", name: "Architect", model_tier: "strong", slot: 2, status: "done" },
        { id: "a4", name: "Reviewer", model_tier: "medium", slot: 3, status: "failed" },
        { id: "a5", name: "DevOps", model_tier: "medium", slot: 4, status: "idle" },
      ],
    },
    {
      id: "t2", name: "Product Planning", template_key: "planning", engine: "crew",
      room_x: 540, room_y: 40,
      agents: [{ id: "b1", name: "PM", model_tier: "strong", slot: 0, status: "queued" }],
    },
    {
      id: "t3", name: "Research", template_key: "research", engine: "crew",
      room_x: 540, room_y: 320,
      agents: [
        { id: "c1", name: "Researcher", model_tier: "medium", slot: 0, status: "working" },
        { id: "c2", name: "Analyst", model_tier: "medium", slot: 1, status: "idle" },
      ],
    },
    {
      id: "t4", name: "Design", template_key: "design", engine: "agent_sdk",
      room_x: 40, room_y: 460, agents: [],
    },
  ],
  edges: [],
};

export default function MapPreview() {
  return (
    <div className="h-screen w-screen">
      <MapCanvas
        data={MOCK}
        callbacks={{
          onSelectAgent: (id) => console.log("agent", id),
          onSelectTeam: (id) => console.log("team", id),
          onDeselect: () => console.log("deselect"),
          onRoomMoved: (id, x, y) => console.log("moved", id, x, y),
        }}
      />
    </div>
  );
}
