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
export const STATUS_CHIP: Record<string, { bg: string; fg: string }> = {
  working: { bg: "#DCEEF8", fg: "#2C6FA0" },
  "needs-input": { bg: "#FBEFCB", fg: "#8A6200" },
  queued: { bg: "#FBEFCB", fg: "#8A6200" },
  done: { bg: "#E0F2E5", fg: "#2C7A4A" },
  failed: { bg: "#F8DAD3", fg: "#B23A26" },
  idle: { bg: "#ECE8DD", fg: "#6A6258" },
  blocked: { bg: "#FBEFCB", fg: "#8A6200" },
};

export const CARPET: Record<string, string> = {
  research: "#C2DAC6",
  development: "#C8D6E4",
  planning: "#DDD3E4",
  design: "#EEE7D6",
  data: "#E2EAD8",
};

// 백엔드 7-상태 → UI 6-비주얼(blocked→needs-input, D36).
export function visualStatus(s: AgentStatus): AgentStatus {
  return s === "blocked" ? "needs-input" : s;
}
