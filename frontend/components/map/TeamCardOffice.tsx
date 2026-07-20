"use client";

// 팀 카드 오피스 — Pixi 캔버스를 대체하는 DOM 카드 레이아웃(승인된 목업).
// 화이트 카드(팀 이모지+이름+상태 pill+1줄 요약) + 이모지 아바타(상태 링/dot). 세로 스크롤.
// 상태는 store 구독으로 실시간 갱신(리렌더). 클릭 → 기존 패널(팀/에이전트).
import { useStore } from "@/lib/store";
import type { MapData, TeamRoom, AgentNode } from "@/lib/map/types";
import { visualStatus, type AgentStatus } from "@/lib/tokens";

// 팀 템플릿 → 이모지 + 액센트/틴트.
// G-Clay(D59): soft = 룸 카펫(파스텔), accent = 좌측 스파인/딥톤, av = 아바타 틴트.
const TEAM: Record<string, { emoji: string; accent: string; soft: string; av: string }> = {
  planning: { emoji: "📋", accent: "#86A8D8", soft: "#BDD1EA", av: "#DCE8F5" },
  research: { emoji: "🔍", accent: "#7DB98A", soft: "#BFD9C6", av: "#DEEFE2" },
  design: { emoji: "🎨", accent: "#C9A96B", soft: "#E7DCC8", av: "#F2EAD9" },
  development: { emoji: "🛠️", accent: "#8D83CF", soft: "#BBB4DF", av: "#E3DFF4" },
  data: { emoji: "📊", accent: "#7FB894", soft: "#CFE4D4", av: "#E4F1E8" },
};
const DEFAULT_TEAM = { emoji: "🏢", accent: "#A9A6B8", soft: "#E6E2F0", av: "#F0EDF7" };

// 상태 → pill/링/dot.
type SK = "idle" | "working" | "needs-input" | "failed" | "done";
// screen = 데스크 모니터 스크린 색(D54: 상태색이 감독 정보 — 글로우는 활성 상태만).
const STATUS: Record<SK, { label: string; pill: string; ring: string; dot: string; glyph: string; screen: string; glow?: string; pulse?: boolean }> = {
  idle: { label: "idle", pill: "bg-[#EFEDF5] text-[#6E6A87]", ring: "rgba(110,106,135,.3)", dot: "#B9B5CC", glyph: "", screen: "#4A4662" },
  working: { label: "working", pill: "bg-[rgba(89,215,255,.2)] text-[#1F7FA8]", ring: "#38B6E8", dot: "#38B6E8", glyph: "↻", screen: "#59D7FF", glow: "rgba(89,215,255,.75)" },
  "needs-input": { label: "needs you", pill: "bg-[#FFF3D6] text-[#96660A]", ring: "#F2A93B", dot: "#F2A93B", glyph: "!", screen: "#FFC848", glow: "rgba(255,200,72,.75)", pulse: true },
  failed: { label: "failed", pill: "bg-[#FBE3DE] text-[#B23A26]", ring: "#E8503A", dot: "#E8503A", glyph: "×", screen: "#FF8A75", glow: "rgba(232,80,58,.65)" },
  done: { label: "done ✓", pill: "bg-gradient-to-br from-[#54C875] to-[#3AA45C] text-white shadow-[0_3px_8px_rgba(67,179,106,.35)]", ring: "#4CC97A", dot: "#4CC97A", glyph: "✓", screen: "#7FE8A2" },
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
    // office-floor = 체커 타일 배경(QA-07) — 단색 대신 오피스 공간감.
    <div className="office-floor h-full w-full overflow-y-auto">
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
      className="relative min-h-[176px] cursor-pointer rounded-[20px] border border-white bg-white/95 p-5 shadow-[0_1px_0_#EBE7F4,0_14px_30px_rgba(110,100,168,.16)] transition-transform hover:-translate-y-[3px] hover:shadow-[0_1px_0_#EBE7F4,0_20px_42px_rgba(110,100,168,.22)]"
    >
      <div className="pointer-events-none absolute bottom-[18px] left-0 top-[18px] w-1 rounded-r" style={{ background: t.accent }} />
      <div className="flex items-center gap-[9px]">
        <span className="grid h-8 w-8 flex-none place-items-center rounded-[10px] text-[17px]" style={{ background: t.soft }}>{t.emoji}</span>
        <span className="truncate font-baloo text-[16px] font-extrabold tracking-tight">{team.name}</span>
        <span className="flex-1" />
        <span className={`flex-none whitespace-nowrap rounded-full px-[11px] py-1 text-[11px] font-extrabold ${pill.pill}`}>{pill.label}</span>
      </div>

      <p className="mt-[9px] break-words text-[12.5px] leading-[1.45] text-muted">
        {team.summary ?? "No tasks yet — give the team something to do"}
      </p>

      {team.agents.length === 0 ? (
        <p className="mt-4 text-[12px] italic text-muted-2">No agents yet — hire your first</p>
      ) : (
        <div
          className="mt-[14px] flex flex-wrap gap-x-[10px] gap-y-[14px] rounded-[14px] px-3 pb-2 pt-3"
          // 룸 카펫(D59) — 팀 컬러 파스텔 + 은은한 타일 그리드. 에이전트는 이 위에 "앉아" 있다.
          style={{
            background: t.soft,
            backgroundImage:
              "linear-gradient(rgba(255,255,255,.22) 1.5px, transparent 1.5px), linear-gradient(90deg, rgba(255,255,255,.22) 1.5px, transparent 1.5px)",
            backgroundSize: "22px 22px",
            boxShadow: "inset 0 2px 6px rgba(70,60,120,.12)",
          }}
        >
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
  // queued도 working 비주얼(cyan 링/↻)로 — 팀 pill(teamPill)이 queued→working과 일치시킨다(감사 P2).
  const sk: SK = v === "queued" ? "working" : ((["working", "needs-input", "failed", "done"].includes(v) ? v : "idle") as SK);
  const s = STATUS[sk];
  return (
    <button
      onClick={(e) => { e.stopPropagation(); onSelect?.(agent.id); }}
      className="w-[64px] text-center outline-none"
      title={agent.name}
    >
      {/* 상태 pill을 머리 위로(QA-02) — 오피스를 훑기만 해도 누가 뭘 하는지 읽히게. working은 pulse. */}
      <span className={`mx-auto mb-1 block w-fit whitespace-nowrap rounded-full px-2 py-px text-[9px] font-extrabold leading-[1.5] ${s.pill} ${sk === "working" ? "animate-pulse" : ""}`}>
        {s.label}
      </span>
      <span className="relative mx-auto block h-[64px] w-[58px]">
        {/* 아바타(뒤) — 데스크에 앉은 구도라 하단이 데스크에 살짝 가려진다 */}
        <span className="absolute left-1/2 top-0 grid h-[40px] w-[40px] -translate-x-1/2 place-items-center rounded-full border-2 border-white text-[20px] shadow-[0_4px_10px_rgba(110,100,168,.2)]" style={{ background: teamAv }}>
          {roleEmoji(agent.name)}
        </span>
        <span className={`absolute left-1/2 top-0 h-[40px] w-[40px] -translate-x-1/2 rounded-full ${s.pulse ? "animate-pulse" : ""}`} style={{ border: `2.5px solid ${s.ring}` }} />
        {/* 데스크(앞) — 화이트 클레이 */}
        <span className="absolute bottom-0 left-1/2 h-[15px] w-[56px] -translate-x-1/2 rounded-[5px] bg-[#FDFCF9] shadow-[0_2px_0_#D5D0C2,0_5px_10px_rgba(110,100,168,.18)]" />
        {/* 모니터 — 스크린 = 상태색, 활성 상태는 글로우(D54: 감독 정보) */}
        <span className="absolute bottom-[7px] left-1/2 h-[17px] w-[24px] -translate-x-1/2 rounded-[3px] bg-[#33304A] p-[2.5px]">
          <span className={`block h-full w-full rounded-[1.5px] ${s.pulse ? "animate-pulse" : ""}`}
            style={{ background: s.screen, boxShadow: s.glow ? `0 0 10px 2px ${s.glow}` : "none" }} />
        </span>
        {s.glyph && (
          <span className="absolute bottom-[10px] right-0 grid h-[15px] w-[15px] place-items-center rounded-full border-2 border-white text-[9px] font-black text-white" style={{ background: s.dot }}>{s.glyph}</span>
        )}
      </span>
      <span
        className="mt-[6px] block break-words font-baloo text-[10.5px] font-extrabold leading-[1.15] text-ink-soft"
        style={{ display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}
      >{agent.name}</span>
      <span className="block font-mono text-[9px] text-muted">{agent.model_tier}</span>
    </button>
  );
}
