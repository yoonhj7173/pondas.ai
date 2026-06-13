// Room 렌더 — 벽 띠 + 체커 바닥 + 카펫 + 행잉 사인 + 그림자(핸드오프 5-slot 시스템).
import { Container, Graphics, Text } from "pixi.js";
import { CARPET } from "@/lib/tokens";

export interface Slot {
  x: number;
  y: number;
  facing: "left" | "right";
}

// 헤드카운트별 방 크기(점진 성장) + 슬롯.
export function roomLayout(count: number): { w: number; h: number; slots: Slot[] } {
  if (count <= 2) {
    return { w: 340, h: 220, slots: [
      { x: 40, y: 88, facing: "left" }, { x: 194, y: 88, facing: "right" },
    ]};
  }
  if (count <= 3) {
    return { w: 410, h: 280, slots: [
      { x: 30, y: 119, facing: "left" }, { x: 274, y: 119, facing: "right" }, { x: 152, y: 119, facing: "right" },
    ]};
  }
  // 5-seat 430×370 — 핸드오프 고정 5슬롯.
  return { w: 430, h: 370, slots: [
    { x: 64, y: 76, facing: "left" }, { x: 260, y: 76, facing: "right" },
    { x: 64, y: 168, facing: "left" }, { x: 260, y: 168, facing: "right" },
    { x: 162, y: 252, facing: "right" },
  ]};
}

const WALL = 42;

export function drawRoomBase(name: string, templateKey: string, w: number, h: number): Container {
  const root = new Container();

  // 그림자.
  const shadow = new Graphics();
  shadow.roundRect(6, 14, w, h, 10).fill({ color: 0x3c4132, alpha: 0.22 });
  root.addChild(shadow);

  // 바닥(체커).
  const floor = new Graphics();
  floor.roundRect(0, 0, w, h, 8).fill(0xf2efe3);
  for (let y = WALL; y < h; y += 32) {
    for (let x = 0; x < w; x += 32) {
      if (((x / 32) + Math.floor((y - WALL) / 32)) % 2 === 0) {
        floor.rect(x, y, 32, 32).fill(0xe2e4d0);
      }
    }
  }
  // 바닥 마스크(라운드 코너 유지).
  const mask = new Graphics().roundRect(0, 0, w, h, 8).fill(0xffffff);
  floor.mask = mask;
  root.addChild(floor, mask);

  // 카펫(팀 아이덴티티) — 인셋.
  const carpet = new Graphics();
  const inset = 16;
  carpet.roundRect(inset, WALL + inset, w - inset * 2, h - WALL - inset - 26, 10)
    .fill(CARPET[templateKey] ?? 0xeee7d6);
  root.addChild(carpet);

  // 벽 띠(상단) — 몰딩 → face.
  const wall = new Graphics();
  wall.rect(0, 0, w, WALL).fill(0xcec09c);
  wall.rect(0, 0, w, WALL - 8).fill(0xd9ccab);
  wall.rect(0, 0, w, 10).fill(0x8a7a5e);
  root.addChild(wall);

  // 행잉 사인 — 네이비 플레이트 + 케이블.
  const sign = new Container();
  const cx = w / 2;
  const cable = new Graphics();
  cable.rect(cx - 40, WALL - 2, 2.5, 14).fill(0x8a7a5e);
  cable.rect(cx + 38, WALL - 2, 2.5, 14).fill(0x8a7a5e);
  sign.addChild(cable);
  const plate = new Graphics();
  const tw = Math.max(96, name.length * 9 + 24);
  plate.roundRect(cx - tw / 2, WALL + 8, tw, 24, 6).fill(0x2e3a52);
  plate.roundRect(cx - tw / 2, WALL + 8, tw, 24, 6).stroke({ color: 0xffffff, width: 2 });
  sign.addChild(plate);
  const label = new Text({ text: name, style: { fontFamily: "Baloo 2, sans-serif", fontSize: 13, fontWeight: "700", fill: 0xffffff } });
  label.anchor.set(0.5);
  label.position.set(cx, WALL + 20);
  sign.addChild(label);
  sign.rotation = (-1.2 * Math.PI) / 180;
  root.addChild(sign);

  return root;
}

export function emptyHintPill(w: number, h: number): Container {
  const c = new Container();
  const g = new Graphics();
  const text = "No agents yet — hire your first";
  const tw = text.length * 6 + 24;
  g.roundRect(-tw / 2, -14, tw, 28, 14).fill({ color: 0xffffff, alpha: 0.8 });
  c.addChild(g);
  const t = new Text({ text, style: { fontFamily: "Nunito, sans-serif", fontSize: 12, fontWeight: "700", fill: 0x8a857c } });
  t.anchor.set(0.5);
  c.addChild(t);
  c.position.set(w / 2, h / 2 + 8);
  return c;
}
