// 알림 사운드(QA-04) — 유저 액션이 필요한 이벤트(needs-input/failed/채팅 답변)에만 짧은 딩.
// 에셋 없이 WebAudio 합성(2음 차임). 브라우저 정책상 첫 유저 제스처 전엔 조용히 무시된다.
let _ctx: AudioContext | null = null;

export function ding(kind: "attention" | "chat" = "attention"): void {
  try {
    _ctx = _ctx ?? new (window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext)();
    const ctx = _ctx;
    if (ctx.state === "suspended") { ctx.resume().catch(() => {}); }
    const t0 = ctx.currentTime;
    // attention = 높은 2음(딩-동), chat = 부드러운 1음.
    const notes = kind === "attention" ? [{ f: 880, at: 0 }, { f: 660, at: 0.12 }] : [{ f: 740, at: 0 }];
    for (const { f, at } of notes) {
      const o = ctx.createOscillator();
      const g = ctx.createGain();
      o.type = "sine";
      o.frequency.value = f;
      g.gain.setValueAtTime(0.0001, t0 + at);
      g.gain.exponentialRampToValueAtTime(0.05, t0 + at + 0.015);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + at + 0.22);
      o.connect(g).connect(ctx.destination);
      o.start(t0 + at);
      o.stop(t0 + at + 0.25);
    }
  } catch { /* 오디오 불가 환경 — 소리는 부가 기능 */ }
}
