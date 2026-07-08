"use client";

// 카드 오피스 + 상태 파이프라인 프리뷰 — 시뮬레이트 버튼이 store.applyStatus를 쏘면
// 팀 카드 pill·아바타 링/dot + 미니 피드가 같은 소스에서 동시에 갱신된다.
import { useEffect } from "react";
import type { MapData } from "@/lib/map/types";
import { useStore } from "@/lib/store";
import type { AgentStatus } from "@/lib/tokens";
import Hud from "@/components/hud/Hud";
import TeamCardOffice from "@/components/map/TeamCardOffice";

const MOCK: MapData = {
  project: { id: "preview", name: "Acme Studio", paused: false },
  paused: false,
  teams: [
    {
      id: "t0", name: "Product Planning", template_key: "planning", engine: "crew",
      room_x: 0, room_y: 0, status: "idle", summary: "PRD v1 handed off to the team",
      agents: [
        { id: "p1", name: "Product Manager", model_tier: "strong", slot: 0, status: "idle" },
        { id: "p2", name: "Business Analyst", model_tier: "medium", slot: 1, status: "idle" },
      ],
    },
    {
      id: "t1", name: "Research", template_key: "research", engine: "crew",
      room_x: 0, room_y: 0, status: "idle",
      summary: "Pulling pricing, menus, and locations from 3 competitor cafés into a comparison table",
      agents: [{ id: "a1", name: "Researcher", model_tier: "strong", slot: 0, status: "idle" }],
    },
    {
      id: "t2", name: "Design", template_key: "design", engine: "agent_sdk",
      room_x: 0, room_y: 0, status: "idle", summary: "Which brand color should I use — sage green or navy?",
      agents: [{ id: "d1", name: "Product Designer", model_tier: "strong", slot: 0, status: "idle" }],
    },
    {
      id: "t3", name: "Development", template_key: "development", engine: "agent_sdk",
      room_x: 0, room_y: 0, status: "idle", summary: "Landing page + café list v1 is done — open the preview",
      agents: [
        { id: "e1", name: "Software Engineer", model_tier: "strong", slot: 0, status: "idle" },
        { id: "e2", name: "Tech Lead", model_tier: "strong", slot: 1, status: "idle" },
        { id: "e3", name: "Architect", model_tier: "strong", slot: 2, status: "idle" },
        { id: "e4", name: "QA Engineer", model_tier: "medium", slot: 3, status: "idle" },
        { id: "e5", name: "DevOps", model_tier: "medium", slot: 4, status: "idle" },
      ],
    },
  ],
  edges: [],
};

export default function MapPreview() {
  useEffect(() => { useStore.getState().setSnapshot(MOCK); }, []);

  function sim(agentId: string, status: AgentStatus) {
    useStore.getState().applyStatus(agentId, status);
  }

  return (
    <div className="relative h-screen w-screen overflow-hidden">
      <TeamCardOffice data={MOCK} onSelectAgent={() => {}} onSelectTeam={() => {}} />
      <Hud projectName="Acme Studio" onSend={() => "On it — Research is investigating; Planning will pick up the output."} />
      <div className="absolute left-1/2 top-4 z-40 flex -translate-x-1/2 gap-1 rounded-tile bg-white/80 p-2 text-sm">
        <Btn onClick={() => sim("a1", "working")}>RES working</Btn>
        <Btn onClick={() => sim("d1", "needs-input")}>DES needs-input</Btn>
        <Btn onClick={() => sim("e1", "failed")}>ENG failed</Btn>
      </div>
    </div>
  );
}

function Btn({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return <button onClick={onClick} className="rounded-pill border-2 border-white bg-primary-to px-2 py-1 text-[11px] font-bold text-white">{children}</button>;
}
