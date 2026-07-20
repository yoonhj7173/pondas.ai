import type { Config } from "tailwindcss";

// G-Clay 디자인 토큰 v2 (D59) — mockups/g-clay-reference.html이 시각 기준.
// 하이키 파스텔 + 클레이 섀도. 토큰 이름은 v1 유지(값만 교체 = 앱 전체 리스킨), D54 필터: 상태색 = 감독 정보.
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // World (low saturation)
        ground: "#F6EFE2",
        floor: "#FDFCF9",
        "floor-checker": "#EFE9DA",
        wall: { molding: "#B5AEDA", face: "#E2DDF1", side: "#D2CCE8" },
        carpet: {
          research: "#BFD9C6",
          development: "#BBB4DF",
          planning: "#BDD1EA",
          design: "#E7DCC8",
          data: "#CFE4D4",
        },
        // UI (candy)
        "primary-from": "#8F84E8",
        "primary-to": "#7266D6",
        "confirm-from": "#54C875",
        "confirm-to": "#3AA45C",
        // Status
        status: {
          working: "#59D7FF",
          "needs-input": "#FFC848",
          queued: "#FFC848",
          done: "#4CC97A",
          failed: "#E8503A",
          idle: "#A8A294",
        },
        navy: "#33304A",
        // Text
        ink: "#33304A",
        "ink-soft": "#3E3A56",
        secondary: "#6E6A87",
        muted: "#8A8798",
        "muted-2": "#A9A6B8",
      },
      // 상태 chip 페어(bg/fg) — README §Colors.
      // 클래스로 직접 쓰기 좋게 별도 정의.
      fontFamily: {
        inter: ["var(--font-inter)", "sans-serif"],
        baloo: ["var(--font-inter)", "sans-serif"], // D59: Baloo 폐기 — 기존 클래스는 Inter로 폴백
        nunito: ["var(--font-inter)", "sans-serif"], // D59: Nunito 폐기 — 기존 클래스는 Inter로 폴백
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
        card: "0 20px 50px rgba(70,60,120,0.28)",
        panel: "0 10px 30px rgba(110,100,168,0.22)",
        room: "0 16px 30px rgba(110,100,168,0.25)",
      },
      backdropBlur: { glass: "10px" },
    },
  },
  plugins: [],
};
export default config;
