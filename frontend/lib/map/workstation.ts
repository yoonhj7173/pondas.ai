// Workstation 컴포넌트 — 에이전트 스프라이트(핸드오프 단일 소스).
// 정면/프로필 뷰 플레이스홀더 지오메트리(D35). 비율/색/앵커/글로우/배지가 스펙.
// 슬롯 풋프린트 106×82, 내부 150×116 드로잉 @ scale 0.7, top-left 앵커.
import { Container, Graphics, Text } from "pixi.js";
import { STATUS_GLOW, STATUS_BADGE, visualStatus, type AgentStatus } from "@/lib/tokens";

// 아웃핏 페어(body/arm) — role에 따라 순환.
const OUTFITS = [
  { body: 0x5fa89b, arm: 0x4e8b80 },
  { body: 0xd98a70, arm: 0xc2755c },
  { body: 0xb58fbf, arm: 0x9a75a3 },
  { body: 0x93a86e, arm: 0x78905a },
  { body: 0xc9a24b, arm: 0xab8736 },
];
const HEADS = [0xefc9a2, 0xe5b98f];

export interface WorkstationHandle {
  container: Container;
  setStatus(status: AgentStatus): void;
  setBadgeScale(s: number): void; // 줌 역보정(화면 고정 크기)
}

export function createWorkstation(opts: {
  facing: "left" | "right";
  outfitIndex: number;
}): WorkstationHandle {
  const root = new Container();

  // 내부 드로잉 컨테이너 — top-left 앵커, scale 0.7.
  const inner = new Container();
  inner.scale.set(0.7);
  root.addChild(inner);

  const outfit = OUTFITS[opts.outfitIndex % OUTFITS.length];
  const head = HEADS[opts.outfitIndex % HEADS.length];

  // 책상.
  const desk = new Graphics();
  desk.roundRect(20, 86, 120, 14, 4).fill(0xfffdf6);
  desk.roundRect(20, 98, 120, 5, 2).fill(0xc9bc9a); // 그림자
  inner.addChild(desk);

  // 스툴/의자.
  const stool = new Graphics();
  stool.roundRect(40, 70, 34, 8, 3).fill(0x8a8170);
  stool.rect(46, 78, 6, 24).fill(0x8a8170);
  stool.rect(62, 78, 6, 24).fill(0x8a8170);
  inner.addChild(stool);

  // 글로우(모니터 뒤) — 상태색. setStatus가 갱신.
  const glow = new Graphics();
  inner.addChildAt(glow, 0);

  // 몸통(살짝 기울임).
  const body = new Graphics();
  body.roundRect(-16, -28, 32, 50, 12).fill(outfit.body);
  body.position.set(56, 56);
  body.rotation = (4 * Math.PI) / 180;
  inner.addChild(body);

  // 팔(키보드로).
  const arm = new Graphics();
  arm.roundRect(0, 0, 30, 9, 4).fill(outfit.arm);
  arm.position.set(58, 70);
  arm.rotation = (10 * Math.PI) / 180;
  inner.addChild(arm);

  // 머리 + 눈.
  const headG = new Graphics();
  headG.circle(56, 26, 16).fill(head);
  headG.circle(62, 24, 2.2).fill(0x4a443a); // 눈
  inner.addChild(headG);

  // 모니터.
  const monitor = new Graphics();
  monitor.roundRect(98, 50, 30, 40, 4).fill(0x2e3a52);
  monitor.rect(110, 90, 6, 8).fill(0x2e3a52);
  monitor.roundRect(100, 96, 26, 4, 2).fill(0x2e3a52);
  inner.addChild(monitor);

  // 배지(머리 위) — 28px 원. 머리 위치는 facing(미러)에 따라 좌/우.
  const badge = new Container();
  const headX = (opts.facing === "right" ? 56 : -56) * 0.7;
  badge.position.set(headX, -2);
  const badgeBg = new Graphics();
  const badgeText = new Text({ text: "", style: { fontFamily: "Baloo 2, sans-serif", fontSize: 18, fontWeight: "800", fill: 0xffffff } });
  badgeText.anchor.set(0.5);
  badge.addChild(badgeBg, badgeText);
  badge.visible = false;
  root.addChild(badge);

  // 미러 facing.
  if (opts.facing === "left") inner.scale.x = -0.7;

  function setStatus(status: AgentStatus) {
    const v = visualStatus(status);
    // 글로우.
    glow.clear();
    const g = STATUS_GLOW[v];
    if (g) {
      const col = glowColor(v);
      glow.roundRect(92, 44, 42, 52, 8).fill({ color: col.color, alpha: col.alpha });
    }
    // 배지.
    const b = STATUS_BADGE[v];
    if (b) {
      badgeBg.clear();
      badgeBg.circle(0, 0, 14).fill(0xffffff);
      badgeBg.circle(0, 0, 12.5).fill(hexNum(b.color));
      badgeText.text = b.glyph;
      badge.visible = true;
    } else {
      badge.visible = false;
    }
  }

  function setBadgeScale(s: number) {
    badge.scale.set(s);
  }

  return { container: root, setStatus, setBadgeScale };
}

function hexNum(hex: string): number {
  return parseInt(hex.replace("#", ""), 16);
}

// rgba 문자열 → {color, alpha} (글로우 토큰이 rgba라서).
function glowColor(v: AgentStatus): { color: number; alpha: number } {
  const map: Record<string, { color: number; alpha: number }> = {
    working: { color: 0x4fc3e8, alpha: 0.55 },
    "needs-input": { color: 0xf7b731, alpha: 0.55 },
    queued: { color: 0xf7b731, alpha: 0.3 },
    done: { color: 0x5fc96e, alpha: 0.55 },
    failed: { color: 0xe8503a, alpha: 0.55 },
  };
  return map[v] ?? { color: 0xffffff, alpha: 0 };
}
