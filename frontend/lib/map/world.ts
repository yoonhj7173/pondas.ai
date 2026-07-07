// PixiWorld — 오피스 맵 렌더 + 카메라(팬/줌, D35) + 인터랙션. React HUD와 분리.
import { Application, Container, Graphics, FederatedPointerEvent } from "pixi.js";
import type { MapData, TeamRoom } from "./types";
import type { AgentStatus } from "@/lib/tokens";
import { drawRoomBase, emptyHintPill, roomLayout, type Slot } from "./room";
import { createWorkstation, type WorkstationHandle } from "./workstation";

const ZOOM_MIN = 0.55;
const ZOOM_MAX = 1.4;
const DRAG_THRESHOLD = 4; // px — 클릭 vs 드래그 구분(D36)

export interface WorldCallbacks {
  onSelectAgent?: (agentId: string) => void;
  onSelectTeam?: (teamId: string) => void;
  onDeselect?: () => void;
  onRoomMoved?: (teamId: string, x: number, y: number) => void;
}

export class PixiWorld {
  app = new Application();
  world = new Container(); // 팬/줌되는 월드 레이어
  private ground = new Graphics();
  private agents = new Map<string, WorkstationHandle>();
  private rooms = new Map<string, Container>();
  private cb: WorldCallbacks;

  // 드래그 상태.
  private dragging: null | { kind: "pan" | "room"; teamId?: string; startX: number; startY: number; moved: boolean; origX: number; origY: number } = null;

  constructor(cb: WorldCallbacks) {
    this.cb = cb;
  }

  async init(canvas: HTMLCanvasElement, w: number, h: number) {
    await this.app.init({ canvas, width: w, height: h, background: 0xc6c9bc, antialias: true, resolution: window.devicePixelRatio || 1, autoDensity: true });
    this.world.addChild(this.ground);
    this.app.stage.addChild(this.world);

    this.app.stage.eventMode = "static";
    this.app.stage.hitArea = this.app.screen;
    this.app.stage.on("pointerdown", this.onDown);
    this.app.stage.on("pointermove", this.onMove);
    this.app.stage.on("pointerup", this.onUp);
    this.app.stage.on("pointerupoutside", this.onUp);
    canvas.addEventListener("wheel", this.onWheel, { passive: false });
  }

  private drawGround() {
    const g = this.ground;
    g.clear();
    const W = 4000, H = 3000;
    g.rect(-W / 2, -H / 2, W, H).fill(0xc6c9bc);
    for (let x = -W / 2; x <= W / 2; x += 42) g.rect(x, -H / 2, 1, H).fill({ color: 0x5a5f50, alpha: 0.06 });
    for (let y = -H / 2; y <= H / 2; y += 42) g.rect(-W / 2, y, W, 1).fill({ color: 0x5a5f50, alpha: 0.06 });
  }

  render(data: MapData) {
    this.drawGround();
    // 기존 방 제거(간단: 전체 재구성 — 상태 갱신은 updateAgentStatus로).
    for (const c of this.rooms.values()) c.destroy({ children: true });
    this.rooms.clear();
    this.agents.clear();

    for (const team of data.teams) this.renderRoom(team);
    this.fit(data.teams);
  }

  private renderRoom(team: TeamRoom) {
    const count = Math.max(1, team.agents.length);
    const { w, h, slots } = roomLayout(count);
    const room = new Container();
    room.position.set(team.room_x, team.room_y);
    room.addChild(drawRoomBase(team.name, team.template_key, w, h));

    // 벽 바 = 팀 선택/드래그 핸들(상단 42px).
    const bar = new Graphics();
    bar.rect(0, 0, w, 42).fill({ color: 0xffffff, alpha: 0.001 });
    bar.eventMode = "static";
    bar.cursor = "grab";
    bar.on("pointerdown", (e: FederatedPointerEvent) => this.startRoomDrag(e, team));
    room.addChild(bar);

    if (team.agents.length === 0) {
      room.addChild(emptyHintPill(w, h));
    } else {
      // 점유 슬롯 바운딩박스를 카펫 중앙 정렬.
      const used = slots.slice(0, Math.min(team.agents.length, slots.length));
      const bbox = bboxOf(used);
      const offX = (w - bbox.w) / 2 - bbox.minX;
      const offY = (h + 42 - bbox.h) / 2 - bbox.minY;
      team.agents.slice(0, slots.length).forEach((agent, i) => {
        const slot = slots[i];
        const ws = createWorkstation({ facing: slot.facing, outfitIndex: i, label: agent.name });
        ws.container.position.set(slot.x + offX - 53, slot.y + offY - 41);
        ws.container.eventMode = "static";
        ws.container.cursor = "pointer";
        ws.container.on("pointertap", () => { if (!this.justDragged) this.cb.onSelectAgent?.(agent.id); });
        ws.setStatus(agent.status);
        room.addChild(ws.container);
        this.agents.set(agent.id, ws);
      });
    }

    this.world.addChild(room);
    this.rooms.set(team.id, room);
  }

  // --- 상태 갱신(item 22) ---
  updateAgentStatus(agentId: string, status: AgentStatus) {
    this.agents.get(agentId)?.setStatus(status);
  }

  // --- 카메라 ---
  fit(teams: TeamRoom[]) {
    if (teams.length === 0) { this.world.position.set(this.app.screen.width / 2, this.app.screen.height / 2); this.world.scale.set(1); this.updateBadges(); return; }
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const t of teams) {
      const { w, h } = roomLayout(Math.max(1, t.agents.length));
      minX = Math.min(minX, t.room_x); minY = Math.min(minY, t.room_y);
      maxX = Math.max(maxX, t.room_x + w); maxY = Math.max(maxY, t.room_y + h);
    }
    const pad = 80;
    const cw = maxX - minX + pad * 2, ch = maxY - minY + pad * 2;
    const scale = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, Math.min(this.app.screen.width / cw, this.app.screen.height / ch)));
    this.world.scale.set(scale);
    this.world.position.set(
      this.app.screen.width / 2 - ((minX + maxX) / 2) * scale,
      this.app.screen.height / 2 - ((minY + maxY) / 2) * scale,
    );
    this.updateBadges();
  }

  private onWheel = (e: WheelEvent) => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.1 : 1 / 1.1;
    const next = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, this.world.scale.x * factor));
    const rect = (e.target as HTMLCanvasElement).getBoundingClientRect();
    const px = e.clientX - rect.left, py = e.clientY - rect.top;
    // 포인터 기준 줌.
    const wx = (px - this.world.x) / this.world.scale.x;
    const wy = (py - this.world.y) / this.world.scale.y;
    this.world.scale.set(next);
    this.world.position.set(px - wx * next, py - wy * next);
    this.updateBadges();
  };

  setZoom(next: number) {
    const z = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, next));
    const cx = this.app.screen.width / 2, cy = this.app.screen.height / 2;
    const wx = (cx - this.world.x) / this.world.scale.x, wy = (cy - this.world.y) / this.world.scale.y;
    this.world.scale.set(z);
    this.world.position.set(cx - wx * z, cy - wy * z);
    this.updateBadges();
  }
  zoom() { return this.world.scale.x; }

  private updateBadges() {
    const s = 1 / this.world.scale.x; // 화면 고정 크기.
    for (const ws of this.agents.values()) ws.setBadgeScale(s);
  }

  // --- 인터랙션 ---
  private justDragged = false;

  private onDown = (e: FederatedPointerEvent) => {
    // 방 드래그가 아니면 팬 시작.
    if (this.dragging) return;
    this.dragging = { kind: "pan", startX: e.global.x, startY: e.global.y, moved: false, origX: this.world.x, origY: this.world.y };
  };

  private startRoomDrag(e: FederatedPointerEvent, team: TeamRoom) {
    const room = this.rooms.get(team.id)!;
    this.dragging = { kind: "room", teamId: team.id, startX: e.global.x, startY: e.global.y, moved: false, origX: room.x, origY: room.y };
  }

  private onMove = (e: FederatedPointerEvent) => {
    if (!this.dragging) return;
    const dx = e.global.x - this.dragging.startX, dy = e.global.y - this.dragging.startY;
    if (!this.dragging.moved && Math.hypot(dx, dy) > DRAG_THRESHOLD) this.dragging.moved = true;
    if (!this.dragging.moved) return;
    if (this.dragging.kind === "pan") {
      this.world.position.set(this.dragging.origX + dx, this.dragging.origY + dy);
    } else {
      const room = this.rooms.get(this.dragging.teamId!)!;
      room.position.set(this.dragging.origX + dx / this.world.scale.x, this.dragging.origY + dy / this.world.scale.y);
    }
  };

  private onUp = (e: FederatedPointerEvent) => {
    if (!this.dragging) return;
    const d = this.dragging;
    this.dragging = null;
    if (!d.moved) {
      // 클릭.
      if (d.kind === "room") this.cb.onSelectTeam?.(d.teamId!);
      else this.cb.onDeselect?.();
      return;
    }
    this.justDragged = true;
    setTimeout(() => (this.justDragged = false), 0);
    if (d.kind === "room") {
      const room = this.rooms.get(d.teamId!)!;
      this.cb.onRoomMoved?.(d.teamId!, Math.round(room.x), Math.round(room.y));
    }
  };

  resize(w: number, h: number) {
    if (!this.app.renderer) return; // init(async) 완료 전 호출 가드.
    this.app.renderer.resize(w, h);
    this.app.stage.hitArea = this.app.screen;
  }

  private _destroyed = false;
  destroy() {
    // 견고화: init(async) 미완료/ResizePlugin 미설정/StrictMode 더블마운트 시 destroy가
    // 던지는 걸 방어(_cancelResize 등). 멱등 + renderer 가드 + try/catch.
    if (this._destroyed) return;
    this._destroyed = true;
    try {
      if ((this.app as unknown as { renderer?: unknown }).renderer) {
        this.app.destroy(true, { children: true });
      }
    } catch {
      /* 미초기화/이미 파기 — 무시 */
    }
  }
}

function bboxOf(slots: Slot[]) {
  const xs = slots.map((s) => s.x), ys = slots.map((s) => s.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  return { minX, minY, w: maxX - minX, h: maxY - minY };
}
