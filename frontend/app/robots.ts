import type { MetadataRoute } from "next";

const BASE = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

// AI 크롤러 명시 허용(GEO) + 인증 게이트 앱 경로는 크롤 제외. 마케팅은 공개.
export default function robots(): MetadataRoute.Robots {
  const aiBots = ["GPTBot", "ClaudeBot", "anthropic-ai", "PerplexityBot", "Google-Extended", "CCBot"];
  return {
    rules: [
      { userAgent: "*", allow: "/", disallow: ["/app/", "/onboarding"] },
      ...aiBots.map((ua) => ({ userAgent: ua, allow: "/" })),
    ],
    sitemap: `${BASE}/sitemap.xml`,
    host: BASE,
  };
}
