import type { MetadataRoute } from "next";
import { allSlugs } from "@/lib/blog";

const BASE = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();
  return [
    { url: `${BASE}/`, lastModified: now, priority: 1 },
    { url: `${BASE}/blog`, lastModified: now, priority: 0.8 },
    ...allSlugs().map((slug) => ({ url: `${BASE}/blog/${slug}`, lastModified: now, priority: 0.6 })),
    // 법률 페이지(공개·색인) — 신뢰 신호 + 커버리지 완전성.
    { url: `${BASE}/terms`, lastModified: now, priority: 0.3 },
    { url: `${BASE}/privacy`, lastModified: now, priority: 0.3 },
    { url: `${BASE}/refunds`, lastModified: now, priority: 0.3 },
  ];
}
