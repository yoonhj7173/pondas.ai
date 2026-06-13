"use client";

// Pixi 맵 캔버스 래퍼 — 동적 import(클라이언트 전용). 데이터는 prop, 인터랙션은 콜백.
import { useEffect, useRef } from "react";
import type { MapData } from "@/lib/map/types";
import { PixiWorld, type WorldCallbacks } from "@/lib/map/world";
import { useStore } from "@/lib/store";

export default function MapCanvas({ data, callbacks }: { data: MapData; callbacks?: WorldCallbacks }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const worldRef = useRef<PixiWorld | null>(null);

  useEffect(() => {
    let world: PixiWorld | null = null;
    let disposed = false;
    let unsub: (() => void) | null = null;
    const wrap = wrapRef.current!;
    (async () => {
      world = new PixiWorld(callbacks ?? {});
      await world.init(canvasRef.current!, wrap.clientWidth, wrap.clientHeight);
      if (disposed) { world.destroy(); return; }
      worldRef.current = world;
      world.render(data);
      // store 구독 — 상태 변경을 Pixi에 명령형으로 반영(React 리렌더 없이, D36).
      unsub = useStore.subscribe((state, prev) => {
        for (const id in state.agents) {
          if (state.agents[id].status !== prev.agents[id]?.status) {
            world!.updateAgentStatus(id, state.agents[id].status);
          }
        }
      });
    })();
    const ro = new ResizeObserver(() => world?.resize(wrap.clientWidth, wrap.clientHeight));
    ro.observe(wrap);
    return () => { disposed = true; unsub?.(); ro.disconnect(); world?.destroy(); worldRef.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 데이터 변경 시 재렌더.
  useEffect(() => { worldRef.current?.render(data); }, [data]);

  return (
    <div ref={wrapRef} className="relative h-full w-full overflow-hidden">
      <canvas ref={canvasRef} className="block" />
      {/* 줌 컨트롤(우측 중앙). */}
      <div className="absolute right-5 top-1/2 flex -translate-y-1/2 flex-col gap-1 rounded-tile bg-[rgba(36,46,66,0.92)] p-1 text-white">
        <button className="h-9 w-9 rounded-lg text-lg font-bold hover:bg-white/10" onClick={() => worldRef.current?.setZoom((worldRef.current?.zoom() ?? 1) * 1.15)}>+</button>
        <button className="h-9 w-9 rounded-lg font-mono text-[10px] hover:bg-white/10" onClick={() => worldRef.current?.render(data)}>fit</button>
        <button className="h-9 w-9 rounded-lg text-lg font-bold hover:bg-white/10" onClick={() => worldRef.current?.setZoom((worldRef.current?.zoom() ?? 1) / 1.15)}>−</button>
      </div>
    </div>
  );
}
