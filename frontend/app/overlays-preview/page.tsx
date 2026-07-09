"use client";

// 오버레이 비주얼 프리뷰 — Settings는 독립 렌더(백엔드 불필요). Board/Outputs는 빈 상태.
import { useState } from "react";
import { BoardOverlay, OutputsOverlay, SettingsOverlay, NotesOverlay } from "@/components/overlays/Overlays";

const noToken = async () => null;

export default function OverlaysPreview() {
  const [k, setK] = useState<"settings" | "board" | "outputs" | "notes">("settings");
  return (
    <div className="relative h-screen w-screen" style={{ background: "#C6C9BC" }}>
      <div className="absolute left-1/2 top-4 z-[60] flex -translate-x-1/2 gap-1 rounded-tile bg-white/80 p-2">
        {(["settings", "board", "outputs", "notes"] as const).map((v) => (
          <button key={v} onClick={() => setK(v)} className="rounded-pill border-2 border-white bg-primary-to px-3 py-1 text-xs font-bold text-white">{v}</button>
        ))}
      </div>
      {k === "settings" && <SettingsOverlay projectId="p" getToken={noToken} projectName="Acme Studio" paused={false} onClose={() => {}} onChanged={() => {}} />}
      {k === "board" && <BoardOverlay projectId="p" getToken={noToken} onClose={() => {}} onFocus={() => {}} />}
      {k === "outputs" && <OutputsOverlay projectId="p" getToken={noToken} onClose={() => {}} />}
      {k === "notes" && <NotesOverlay projectId="p" getToken={noToken} onClose={() => {}} />}
    </div>
  );
}
