import type { MetadataRoute } from "next";
import { allPosts } from "@/lib/blog";

const BASE = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();
  return [
    { url: `${BASE}/`, lastModified: now, changeFrequency: "weekly", priority: 1 },
    { url: `${BASE}/blog`, lastModified: now, changeFrequency: "weekly", priority: 0.8 },
    // 블로그 글 — lastModified는 frontmatter date(빌드시각 아님). 새 글은 파일 추가만으로 자동 반영.
    ...allPosts().map((p) => ({
      url: `${BASE}/blog/${p.slug}`,
      lastModified: new Date(p.date),
      changeFrequency: "monthly" as const,
      priority: 0.6,
    })),
    // 법률 페이지(공개·색인) — 신뢰 신호 + 커버리지 완전성.
    { url: `${BASE}/terms`, lastModified: now, changeFrequency: "yearly", priority: 0.3 },
    { url: `${BASE}/privacy`, lastModified: now, changeFrequency: "yearly", priority: 0.3 },
    { url: `${BASE}/refunds`, lastModified: now, changeFrequency: "yearly", priority: 0.3 },
  ];
}
