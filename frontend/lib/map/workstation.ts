// Workstation 컴포넌트 — 에이전트 스프라이트(핸드오프 단일 소스).
// 시안 B(아바타 워크스테이션): 역할색 원형 아바타 + 모노그램 + 상태 링 + 모니터 글로우 + 오버헤드 배지.
// 프로시저럴 몸통/머리/팔을 없애 파손 원인을 제거 — 결정적 지오메트리라 어떤 줌에서도 안 깨진다.
// 슬롯 풋프린트 106×82, 내부 드로잉 150×116 @ scale 0.7, top-left 앵커(world의 -53/-41 중심정렬 호환).
import { Container, Graphics, Text } from "pixi.js";
import { STATUS_GLOW, STATUS_BADGE, visualStatus, type AgentStatus } from "@/lib/tokens";

// 역할별 아바타 색(순환) — 기존 아웃핏 팔레트 유지.
const AVATAR_COLORS = [0x5fa89b, 0xd98a70, 0xb58fbf, 0x93a86e, 0xc9a24b];

export interface WorkstationHandle {
  container: Container;
  setStatus(status: AgentStatus): void;
  setBadgeScale(s: number): void; // 줌 역보정(화면 고정 크기)
}

export function createWorkstation(opts: {
  facing: "left" | "right";
  outfitIndex: number;
  label?: string;
}): WorkstationHandle {
  const root = new Container();

  // 내부 드로잉 — top-left 앵커, scale 0.7. 구성은 (75,58) 중심으로 배치.
  const inner = new Container();
  inner.scale.set(0.7);
  root.addChild(inner);

  const color = AVATAR_COLORS[opts.outfitIndex % AVATAR_COLORS.length];
  const cx = 75, cy = 46, R = 25;
  const monRight = opts.facing !== "left";
  const monX = monRight ? 104 : 22; // 모니터가 안쪽(카펫 중앙)을 보게.

  // 글로우(모니터 뒤) — 상태색. setStatus가 갱신.
  const glow = new Graphics();
  inner.addChild(glow);

  // 모니터(작게).
  const monitor = new Graphics();
  monitor.roundRect(monX, 54, 24, 30, 4).fill(0x242e42);
  monitor.rect(monX + 9, 84, 6, 6).fill(0x242e42);
  monitor.roundRect(monX + 2, 90, 20, 4, 2).fill(0x242e42);
  const screen = new Graphics(); // 스크린 틴트(상태색) — setStatus가 갱신.
  inner.addChild(monitor, screen);

  // 상태 링(아바타 테두리) — setStatus가 색 갱신.
  const ring = new Graphics();
  inner.addChild(ring);

  // 아바타 원 + 시트(가짜 구체감) + 화이트 테두리.
  const avatar = new Graphics();
  avatar.circle(cx, cy, R + 2.5).fill(0xffffff);          // 흰 테두리
  avatar.circle(cx, cy, R).fill(color);                    // 역할색
  avatar.circle(cx - 8, cy - 9, R * 0.62).fill({ color: 0xffffff, alpha: 0.22 }); // 상단 하이라이트
  inner.addChild(avatar);

  // 모노그램(이니셜) — 결정적 렌더(이모지 파손 회피).
  const mono = initials(opts.label);
  const monoText = new Text({
    text: mono,
    style: { fontFamily: "Baloo 2, sans-serif", fontSize: mono.length > 1 ? 20 : 24, fontWeight: "800", fill: 0xffffff },
  });
  monoText.anchor.set(0.5);
  monoText.position.set(cx, cy + 1);
  inner.addChild(monoText);

  // 책상(아바타 앞) — 앉은 느낌.
  const desk = new Graphics();
  desk.roundRect(18, 74, 114, 15, 6).fill(0xfbf7ec);
  desk.roundRect(18, 86, 114, 5, 2).fill(0xd8cbab); // 앞면 그림자
  inner.addChild(desk);

  // 이름표(선택) — 책상 아래 작게.
  if (opts.label) {
    const nm = new Text({
      text: truncate(opts.label, 12),
      style: { fontFamily: "Baloo 2, sans-serif", fontSize: 13, fontWeight: "700", fill: 0x55514a },
    });
    nm.anchor.set(0.5);
    nm.position.set(cx, 103);
    inner.addChild(nm);
  }

  // 배지 — 아바타 우상단 코너 칩(inner 안에서 렌더 = 확실). 주의/완료 상태의 !/✓/× 글리프.
  const badgeCX = cx + R * 0.72, badgeCY = cy - R * 0.72;
  const badge = new Container();
  badge.position.set(badgeCX, badgeCY);
  const badgeBg = new Graphics();
  const badgeText = new Text({ text: "", style: { fontFamily: "Baloo 2, sans-serif", fontSize: 13, fontWeight: "800", fill: 0xffffff } });
  badgeText.anchor.set(0.5);
  badgeText.position.set(0, 0.5);
  badge.addChild(badgeBg, badgeText);
  badge.visible = false;
  inner.addChild(badge);

  function setStatus(status: AgentStatus) {
    const v = visualStatus(status);
    const gc = glowColor(v);

    // 상태 링.
    ring.clear();
    if (gc.alpha > 0) {
      ring.circle(cx, cy, R + 5).stroke({ color: gc.color, width: 3.5, alpha: 0.95 });
    } else {
      ring.circle(cx, cy, R + 5).stroke({ color: 0x9a978a, width: 2.5, alpha: 0.5 }); // idle 회색 링
    }

    // 모니터 스크린 틴트 + 뒤 글로우.
    glow.clear();
    screen.clear();
    const scr = gc.alpha > 0 ? gc.color : 0x3a4358;
    screen.roundRect(monX + 3, 57, 18, 20, 2).fill({ color: scr, alpha: gc.alpha > 0 ? 0.9 : 0.5 });
    if (STATUS_GLOW[v]) {
      glow.roundRect(monX - 4, 48, 32, 44, 8).fill({ color: gc.color, alpha: 0.4 });
    }

    // 코너 배지(주의/완료 상태의 글리프).
    const b = STATUS_BADGE[v];
    if (b) {
      badgeBg.clear();
      badgeBg.circle(0, 0, 10.5).fill(0xffffff);
      badgeBg.circle(0, 0, 9).fill(hexNum(b.color));
      badgeText.text = b.glyph;
      badge.visible = true;
    } else {
      badge.visible = false;
    }
  }

  // 인터페이스 유지(world가 호출) — 코너 배지는 아바타와 함께 스케일되어 별도 역보정 불필요.
  function setBadgeScale(_s: number) {}

  return { container: root, setStatus, setBadgeScale };
}

// 이름 → 최대 2자 이니셜(대문자). 없으면 "•".
function initials(label?: string): string {
  if (!label) return "•";
  const words = label.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "•";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

function hexNum(hex: string): number {
  return parseInt(hex.replace("#", ""), 16);
}

// 상태 → {color, alpha}. alpha 0 = 무색(idle).
function glowColor(v: AgentStatus): { color: number; alpha: number } {
  const map: Record<string, { color: number; alpha: number }> = {
    working: { color: 0x3fb4dc, alpha: 0.9 },
    "needs-input": { color: 0xefb43e, alpha: 0.9 },
    queued: { color: 0xefb43e, alpha: 0.45 },
    done: { color: 0x4dbb5c, alpha: 0.9 },
    failed: { color: 0xe8503a, alpha: 0.9 },
  };
  return map[v] ?? { color: 0xffffff, alpha: 0 };
}
