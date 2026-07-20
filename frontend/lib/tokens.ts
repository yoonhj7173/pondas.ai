// 디자인 토큰의 TS 표현 — HUD/카드 오피스가 공유하는 raw 값(Tailwind는 클래스, 여기는 런타임 계산용).

export type AgentStatus =
  | "idle"
  | "queued"
  | "working"
  | "blocked"
  | "needs-input"
  | "done"
  | "failed";

// 상태 chip 페어(bg/fg) — README §Colors.
// G-Clay v2 (D59) — 파스텔 배경 + 딥 포그라운드.
export const STATUS_CHIP: Record<string, { bg: string; fg: string }> = {
  working: { bg: "#E3F4FD", fg: "#1F7FA8" },
  "needs-input": { bg: "#FFF3D6", fg: "#96660A" },
  queued: { bg: "#FFF3D6", fg: "#96660A" },
  done: { bg: "#E2F7EA", fg: "#237A46" },
  failed: { bg: "#FBE3DE", fg: "#B23A26" },
  idle: { bg: "#EFEDF5", fg: "#6E6A87" },
  blocked: { bg: "#FFF3D6", fg: "#96660A" },
};

export const CARPET: Record<string, string> = {
  research: "#BFD9C6",
  development: "#BBB4DF",
  planning: "#BDD1EA",
  design: "#E7DCC8",
  data: "#CFE4D4",
};

// 백엔드 7-상태 → UI 6-비주얼(blocked→needs-input, D36).
export function visualStatus(s: AgentStatus): AgentStatus {
  return s === "blocked" ? "needs-input" : s;
}
