// 블로그 포스트 로더 — content/blog/*.mdx 프론트매터 + 본문(SSG, D33).
import fs from "fs";
import path from "path";
import matter from "gray-matter";

const DIR = path.join(process.cwd(), "content", "blog");

export interface PostMeta {
  slug: string;
  title: string;
  summary: string;
  category: string;
  author: string;
  date: string;
  readTime: string;
}
export interface Post extends PostMeta {
  content: string;
}

export const CATEGORY_CHIP: Record<string, { bg: string; fg: string }> = {
  Engineering: { bg: "#DCEEF8", fg: "#2C6FA0" },
  Product: { bg: "#ECE4F6", fg: "#6B4FA0" },
  Design: { bg: "#E0F2E5", fg: "#2C7A4A" },
};

export function allSlugs(): string[] {
  if (!fs.existsSync(DIR)) return [];
  return fs.readdirSync(DIR).filter((f) => f.endsWith(".mdx")).map((f) => f.replace(/\.mdx$/, ""));
}

export function getPost(slug: string): Post {
  const raw = fs.readFileSync(path.join(DIR, `${slug}.mdx`), "utf8");
  const { data, content } = matter(raw);
  return { slug, content, ...(data as Omit<PostMeta, "slug">) };
}

export function allPosts(): PostMeta[] {
  return allSlugs()
    .map((s) => { const { content, ...meta } = getPost(s); return meta; })
    .sort((a, b) => (a.date < b.date ? 1 : -1));
}
