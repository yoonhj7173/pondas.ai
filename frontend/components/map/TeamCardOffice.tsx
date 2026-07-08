"use client";

// 팀 카드 오피스 — Pixi 캔버스를 대체하는 DOM 카드 레이아웃(승인된 목업).
// 화이트 카드(팀 이모지+이름+상태 pill+1줄 요약) + 이모지 아바타(상태 링/dot). 세로 스크롤.
// 상태는 store 구독으로 실시간 갱신(리렌더). 클릭 → 기존 패널(팀/에이전트).
import { useStore } from "@/lib/store";
import type { MapData, TeamRoom, AgentNode } from "@/lib/map/types";
import { visualStatus, type AgentStatus } from "@/lib/tokens";

// 팀 템플릿 → 이모지 + 액센트/틴트.
const TEAM: Record<string, { emoji: string; accent: string; soft: string; av: string }> = {
  planning: { emoji: "📋", accent: "#8fa9cf", soft: "#dfe7f0", av: "#e7ecf4" },
  research: { emoji: "🔍", accent: "#8fb886", soft: "#e4eede", av: "#e6f0e1" },
  design: { emoji: "🎨", accent: "#c69ac4", soft: "#f0e4ef", av: "#f2e5f1" },
  development: { emoji: "🛠️", accent: "#8b9dc0", soft: "#e6ebf2", av: "#e7ebf3" },
  data: { emoji: "📊", accent: "#c9a24b", soft: "#efe7d1", av: "#efe7d1" },
};
const DEFAULT_TEAM = { emoji: "🏢", accent: "#9aa08e", soft: "#e8e9df", av: "#eceee4" };

// 상태 → pill/링/dot.
type SK = "idle" | "working" | "needs-input" | "failed" | "done";
const STATUS: Record<SK, { label: string; pill: string; ring: string; dot: string; glyph: string; pulse?: boolean }> = {
  idle: { label: "idle", pill: "bg-[#edeee6] text-[#8a887c]", ring: "rgba(120,118,105,.35)", dot: "#b7b6ab", glyph: "" },
  working: { label: "working", pill: "bg-[rgba(63,180,220,.15)] text-[#2f9fc7]", ring: "#3fb4dc", dot: "#3fb4dc", glyph: "↻" },
  "needs-input": { label: "needs you", pill: "bg-[rgba(239,180,62,.22)] text-[#a6710f]", ring: "#efb43e", dot: "#efb43e", glyph: "!", pulse: true },
  failed: { label: "failed", pill: "bg-[rgba(232,80,58,.16)] text-[#c0341f]", ring: "#e8503a", dot: "#e8503a", glyph: "×" },
  done: { label: "done ✓", pill: "bg-gradient-to-br from-[#74d982] to-[#4dbb5c] text-white shadow-[0_3px_8px_rgba(77,187,92,.32)]", ring: "#4dbb5c", dot: "#4dbb5c", glyph: "✓" },
};

// 역할명 → 이모지(휴리스틱, 부분일치).
function roleEmoji(name: string): string {
  const n = name.toLowerCase();
  if (n.includes("product manager") || n === "pm") return "👩🏻‍💼";
  if (n.includes("analyst") || n.includes("business")) return "🧑🏽‍💻";
  if (n.includes("research")) return "🧐";
  if (n.includes("design")) return "👩🏼‍🎨";
  if (n.includes("qa") || n.includes("quality") || n.includes("test")) return "🧑🏽‍🔬";
  if (n.includes("architect")) return "🧑🏻‍🎓";
  if (n.includes("review")) return "🕵🏽";
  if (n.includes("devops") || n.includes("ops") || n.includes("deploy")) return "🧑🏾‍🔧";
  if (n.includes("lead")) return "🧑🏿‍💻";
  if (n.includes("data")) return "📊";
  if (n.includes("engineer") || n.includes("developer") || n.includes("swe")) return "👨🏻‍💻";
  return "🧑‍💻";
}

// 팀 pill = 실시간 에이전트 상태 우선(주의 상태), done/idle은 API 스냅샷.
function teamPill(apiStatus: string | undefined, live: AgentStatus[]): SK {
  if (live.some((s) => s === "needs-input" || s === "blocked")) return "needs-input";
  if (live.some((s) => s === "failed")) return "failed";
  if (live.some((s) => s === "working" || s === "queued")) return "working";
  return apiStatus === "done" ? "done" : "idle";
}

export default function TeamCardOffice({
  data, onSelectTeam, onSelectAgent,
}: {
  data: MapData;
  onSelectTeam?: (id: string) => void;
  onSelectAgent?: (id: string) => void;
}) {
  // store의 실시간 에이전트 상태(스냅샷보다 우선).
  const liveAgents = useStore((s) => s.agents);
  const liveStatus = (a: AgentNode): AgentStatus =>
    (liveAgents[a.id]?.status as AgentStatus) ?? a.status;

  return (
    // 세로 중앙정렬(콘텐츠 짧으면 가운데, 많으면 스크롤) + 상하 여백으로 HUD 밴드(상단 스위처/Activity,
    // 하단 챗바) 겹침 회피. min-h-full + items-center = "맞으면 중앙, 넘치면 스크롤"의 정석.
    <div className="h-full w-full overflow-y-auto">
      <div className="flex min-h-full items-center justify-center px-5 pb-28 pt-20">
        <div className="grid w-full max-w-[720px] grid-cols-1 gap-5 sm:grid-cols-2">
          {data.teams.map((team) => (
            <TeamCard key={team.id} team={team} liveStatus={liveStatus}
              onSelectTeam={onSelectTeam} onSelectAgent={onSelectAgent} />
          ))}
        </div>
      </div>
    </div>
  );
}

function TeamCard({
  team, liveStatus, onSelectTeam, onSelectAgent,
}: {
  team: TeamRoom;
  liveStatus: (a: AgentNode) => AgentStatus;
  onSelectTeam?: (id: string) => void;
  onSelectAgent?: (id: string) => void;
}) {
  const t = TEAM[team.template_key] ?? DEFAULT_TEAM;
  const statuses = team.agents.map(liveStatus);
  const pill = STATUS[teamPill(team.status, statuses)];

  return (
    <div
      onClick={() => onSelectTeam?.(team.id)}
      className="relative cursor-pointer rounded-[20px] border border-white bg-white/95 p-4 shadow-[0_1px_0_#e6e7dd,0_14px_30px_rgba(50,55,45,.13)] transition-transform hover:-translate-y-[3px] hover:shadow-[0_1px_0_#e6e7dd,0_20px_42px_rgba(50,55,45,.18)]"
    >
      <div className="pointer-events-none absolute bottom-[18px] left-0 top-[18px] w-1 rounded-r" style={{ background: t.accent }} />
      <div className="flex items-center gap-[9px]">
        <span className="grid h-8 w-8 flex-none place-items-center rounded-[10px] text-[17px]" style={{ background: t.soft }}>{t.emoji}</span>
        <span className="truncate font-baloo text-[16px] font-extrabold tracking-tight">{team.name}</span>
        <span className="flex-1" />
        <span className={`flex-none whitespace-nowrap rounded-full px-[11px] py-1 text-[11px] font-extrabold ${pill.pill}`}>{pill.label}</span>
      </div>

      <p className="mt-[9px] break-words text-[12.5px] leading-[1.45] text-[#8f8c7e]">
        {team.summary ?? "No tasks yet — give the team something to do"}
      </p>

      {team.agents.length === 0 ? (
        <p className="mt-4 text-[12px] italic text-[#a9a89c]">No agents yet — hire your first</p>
      ) : (
        <div className="mt-[15px] flex flex-wrap gap-x-[18px] gap-y-[14px]">
          {team.agents.map((a) => (
            <AgentAvatar key={a.id} agent={a} teamAv={t.av} status={liveStatus(a)}
              onSelect={onSelectAgent} />
          ))}
        </div>
      )}
    </div>
  );
}

function AgentAvatar({
  agent, teamAv, status, onSelect,
}: {
  agent: AgentNode; teamAv: string; status: AgentStatus; onSelect?: (id: string) => void;
}) {
  const v = visualStatus(status);
  const s = STATUS[(["working", "needs-input", "failed", "done", "idle"].includes(v) ? v : "idle") as SK];
  return (
    <button
      onClick={(e) => { e.stopPropagation(); onSelect?.(agent.id); }}
      className="w-[54px] text-center outline-none"
      title={agent.name}
    >
      <span className="relative mx-auto block h-[46px] w-[46px]">
        <span className="grid h-[46px] w-[46px] place-items-center rounded-full border-[2.5px] border-white text-[23px] shadow-[0_4px_10px_rgba(50,55,45,.16)]" style={{ background: teamAv }}>
          {roleEmoji(agent.name)}
        </span>
        <span className={`absolute rounded-full ${s.pulse ? "animate-pulse" : ""}`} style={{ inset: -3, border: `2.5px solid ${s.ring}` }} />
        {s.glyph && (
          <span className="absolute -bottom-px -right-px grid h-[15px] w-[15px] place-items-center rounded-full border-[2.5px] border-white font-baloo text-[9px] font-black text-white" style={{ background: s.dot }}>{s.glyph}</span>
        )}
      </span>
      <span className="mt-[6px] block truncate font-baloo text-[10.5px] font-extrabold text-[#55514a]">{agent.name}</span>
      <span className="block font-mono text-[9px] text-[#8f8c7e]">{agent.model_tier}</span>
    </button>
  );
}
