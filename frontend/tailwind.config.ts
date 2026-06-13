import type { Config } from "tailwindcss";

// 핸드오프 디자인 토큰(D36) — claude-design-handoff/product/README.md.
// two-layer 룰: 고채도는 클릭/주의 대상에만, 월드는 차분하게.
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // World (low saturation)
        ground: "#C6C9BC",
        floor: "#F2EFE3",
        "floor-checker": "#E2E4D0",
        wall: { molding: "#8A7A5E", face: "#D9CCAB", side: "#C9BC9A" },
        carpet: {
          research: "#C2DAC6",
          development: "#C8D6E4",
          planning: "#DDD3E4",
          design: "#EEE7D6",
          data: "#E2EAD8",
        },
        // UI (candy)
        "primary-from": "#67D2F2",
        "primary-to": "#3FB4DC",
        "confirm-from": "#74D982",
        "confirm-to": "#4DBB5C",
        // Status
        status: {
          working: "#4FC3E8",
          "needs-input": "#F7B731",
          queued: "#F7B731",
          done: "#5FC96E",
          failed: "#E8503A",
          idle: "#A8A294",
        },
        navy: "#2E3A52",
        // Text
        ink: "#2C2925",
        "ink-soft": "#3A3631",
        secondary: "#5C574F",
        muted: "#8A857C",
        "muted-2": "#A8A294",
      },
      // 상태 chip 페어(bg/fg) — README §Colors.
      // 클래스로 직접 쓰기 좋게 별도 정의.
      fontFamily: {
        baloo: ["var(--font-baloo)", "sans-serif"],
        nunito: ["var(--font-nunito)", "sans-serif"],
        mono: ["var(--font-mono)", "monospace"],
        mulish: ["var(--font-mulish)", "sans-serif"],
        bricolage: ["var(--font-bricolage)", "sans-serif"],
      },
      borderRadius: {
        pill: "999px",
        card: "24px",
        tile: "16px",
      },
      boxShadow: {
        card: "0 30px 70px rgba(30,35,25,0.4)",
        panel: "8px 0 34px rgba(50,55,45,0.17)",
        room: "0 14px 16px rgba(60,65,50,0.3)",
      },
      backdropBlur: { glass: "10px" },
    },
  },
  plugins: [],
};
export default config;
