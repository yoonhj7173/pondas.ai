"use client";

// 공유 UI 프리미티브(D36 핸드오프) — 다운스트림 화면이 ad-hoc 스타일 대신 이걸 재사용한다.
import clsx from "clsx";
import { STATUS_CHIP, type AgentStatus, visualStatus } from "@/lib/tokens";

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "confirm" | "danger";
};

export function PillButton({ variant = "primary", className, ...props }: ButtonProps) {
  return (
    <button
      className={clsx(
        "btn-pill text-[15px]",
        variant === "primary" && "btn-primary",
        variant === "confirm" && "btn-confirm",
        variant === "danger" && "btn-danger",
        "disabled:opacity-50 disabled:cursor-not-allowed transition-transform active:scale-[0.97]",
        className,
      )}
      {...props}
    />
  );
}

export function StatusChip({ status }: { status: AgentStatus }) {
  const v = visualStatus(status);
  const pair = STATUS_CHIP[v] ?? STATUS_CHIP.idle;
  return (
    <span
      className="inline-flex items-center rounded-pill px-2.5 py-0.5 font-nunito text-[11px] font-bold"
      style={{ backgroundColor: pair.bg, color: pair.fg }}
    >
      {v}
    </span>
  );
}

export function GlassPanel({ className, children }: { className?: string; children: React.ReactNode }) {
  // 사이드 패널 — width 372px, glassy.
  return (
    <div className={clsx("glass w-[372px] rounded-r-card p-5", className)}>{children}</div>
  );
}

export function DarkTile({ className, children }: { className?: string; children: React.ReactNode }) {
  return <div className={clsx("dark-tile p-3", className)}>{children}</div>;
}

export function Overlay({ onClose, children }: { onClose?: () => void; children: React.ReactNode }) {
  // 중앙 모달/오버레이 프레임 — dim 배경 + radius 24 카드 + 3px white border.
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: "var(--modal-dim)" }}
      onClick={onClose}
    >
      <div
        className="rounded-card border border-[#E4DFEF] bg-white shadow-card"
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}

export function Stepper({ steps, current }: { steps: string[]; current: number }) {
  // done = 초록 체크, active = 큰 파랑, future = beige.
  return (
    <div className="flex items-center gap-2">
      {steps.map((label, i) => {
        const done = i < current;
        const active = i === current;
        return (
          <div key={label} className="flex items-center gap-2">
            <div
              className={clsx(
                "flex items-center justify-center rounded-full font-inter font-bold text-white",
                active ? "h-9 w-9 text-[15px]" : "h-7 w-7 text-[12px]",
              )}
              style={{
                background: done ? "#4CC97A" : active ? "linear-gradient(160deg,#8F84E8,#7266D6)" : "#E6E2F0",
                color: done || active ? "#fff" : "#8A8798",
              }}
            >
              {done ? "✓" : i + 1}
            </div>
            {i < steps.length - 1 && <div className="h-0.5 w-6 rounded bg-floor-checker" />}
          </div>
        );
      })}
    </div>
  );
}
