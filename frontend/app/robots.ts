import type { MetadataRoute } from "next";

const BASE = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

// 비공개/개발용 경로 — 색인·크롤 대상 아님.
//   인증 게이트: /app · /onboarding(로그인 퍼널) · /billing(결제)  |  API: /api
//   개발 프리뷰: /design · /*-preview — 전부 "use client"라 metadata noindex export가 불가능 →
//   robots disallow로 크롤 차단(외부 링크·sitemap 진입점 0이라 이것만으로 색인 위험 제거).
const DISALLOW = [
  "/app",
  "/onboarding",
  "/billing",
  "/api",
  "/design",
  "/map-preview",
  "/overlays-preview",
  "/panels-preview",
];

// AI 답변엔진 크롤러(GEO) — 명시 허용. 단, 비공개 경로는 이들에게도 동일 차단(/app 등 크롤 방지).
const AI_BOTS = [
  "GPTBot",
  "OAI-SearchBot",
  "ChatGPT-User",
  "ClaudeBot",
  "anthropic-ai",
  "PerplexityBot",
  "Google-Extended",
  "CCBot",
];

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      { userAgent: "*", allow: "/", disallow: DISALLOW },
      { userAgent: AI_BOTS, allow: "/", disallow: DISALLOW },
    ],
    sitemap: `${BASE}/sitemap.xml`,
    host: BASE,
  };
}
