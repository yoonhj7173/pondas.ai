"use client";

// 맵 + 상태 파이프라인 프리뷰 — 시뮬레이트 버튼이 store.applyStatus를 쏘면
// 맵 글로우/배지 + 미니 피드가 같은 소스에서 동시에 갱신된다(item 22 증명).
import { useEffect } from "react";
import dynamic from "next/dynamic";
import type { MapData } from "@/lib/map/types";
import { useStore } from "@/lib/store";
import type { AgentStatus } from "@/lib/tokens";

const MapCanvas = dynamic(() => import("@/components/map/MapCanvas"), { ssr: false });

const MOCK: MapData = {
  project: { id: "preview", name: "Acme Studio", paused: false },
  paused: false,
  teams: [
    {
      id: "t1", name: "Development", template_key: "development", engine: "agent_sdk",
      room_x: 40, room_y: 40,
      agents: [
        { id: "a1", name: "SWE", model_tier: "strong", slot: 0, status: "idle" },
        { id: "a2", name: "QA", model_tier: "medium", slot: 1, status: "idle" },
      ],
    },
    {
      id: "t2", name: "Product Planning", template_key: "planning", engine: "crew",
      room_x: 540, room_y: 40,
      agents: [{ id: "b1", name: "PM", model_tier: "strong", slot: 0, status: "idle" }],
    },
  ],
  edges: [],
};

export default function MapPreview() {
  useEffect(() => { useStore.getState().setSnapshot(MOCK); }, []);
  const events = useStore((s) => s.events);

  function sim(agentId: string, status: AgentStatus) {
    useStore.getState().applyStatus(agentId, status);
  }

  return (
    <div className="relative h-screen w-screen">
      <MapCanvas data={MOCK} />
      {/* 시뮬레이트 컨트롤 */}
      <div className="absolute left-4 top-4 z-10 flex flex-col gap-2 rounded-tile bg-white/80 p-3 text-sm">
        <div className="font-baloo font-bold">Simulate</div>
        <div className="flex gap-1">
          <Btn onClick={() => sim("a1", "working")}>SWE working</Btn>
          <Btn onClick={() => sim("a2", "needs-input")}>QA needs-input</Btn>
          <Btn onClick={() => sim("b1", "failed")}>PM failed</Btn>
        </div>
      </div>
      {/* 미니 피드 — events 투영(맵과 같은 소스) */}
      <div className="absolute right-4 top-4 z-10 w-72 rounded-tile bg-[rgba(36,46,66,0.92)] p-3 text-white">
        <div className="mb-2 font-baloo text-sm font-bold">Activity</div>
        {events.length === 0 && <div className="text-xs opacity-50">no events yet</div>}
        {events.map((e) => (
          <div key={e.id} className="border-b border-white/10 py-1 font-nunito text-[11px]">
            [{e.team}] {e.agent} <span style={{ color: chip(e.status) }}>{e.status}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function Btn({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return <button onClick={onClick} className="rounded-pill border-2 border-white bg-primary-to px-2 py-1 text-[11px] font-bold text-white">{children}</button>;
}

function chip(s: string): string {
  return ({ working: "#67D2F2", "needs-input": "#F7B731", failed: "#E8503A", done: "#5FC96E" } as Record<string, string>)[s] ?? "#A8A294";
}
