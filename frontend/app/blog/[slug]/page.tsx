import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Footer, Logo } from "@/components/marketing/shared";
import { allSlugs, getPost, CATEGORY_CHIP } from "@/lib/blog";

export function generateStaticParams() {
  return allSlugs().map((slug) => ({ slug }));
}

export function generateMetadata({ params }: { params: { slug: string } }): Metadata {
  if (!allSlugs().includes(params.slug)) return {};
  const p = getPost(params.slug);
  return {
    title: `${p.title} — Craft`,
    description: p.summary,
    alternates: { canonical: `/blog/${p.slug}` },
    openGraph: { title: p.title, description: p.summary, type: "article", url: `/blog/${p.slug}` },
  };
}

export default function Post({ params }: { params: { slug: string } }) {
  if (!allSlugs().includes(params.slug)) notFound();
  const p = getPost(params.slug);
  const c = CATEGORY_CHIP[p.category] ?? { bg: "#ECE8DD", fg: "#6A6258" };

  const articleJsonLd = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: p.title,
    description: p.summary,
    datePublished: p.date,
    author: { "@type": "Person", name: p.author },
  };

  return (
    <div className="min-h-screen bg-[#FBFAF6] font-mulish text-ink">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(articleJsonLd) }} />
      <nav className="border-b border-black/5 px-6 py-4 md:px-10"><Logo sub="Blog" /></nav>

      <article className="mx-auto max-w-2xl px-6 py-12">
        <Link href="/blog" className="font-nunito text-sm font-bold text-primary-to">← All posts</Link>
        <span className="mt-5 inline-block rounded-pill px-3 py-0.5 font-nunito text-xs font-bold" style={{ background: c.bg, color: c.fg }}>{p.category}</span>
        <h1 className="mt-3 font-baloo text-4xl font-extrabold leading-tight">{p.title}</h1>
        <div className="mt-4 flex items-center gap-3 font-nunito text-sm text-secondary">
          <span className="flex h-9 w-9 items-center justify-center rounded-full bg-[#E2E4D0] font-baloo font-extrabold text-ink">{p.author.slice(0, 1)}</span>
          <span>{p.author} · {new Date(p.date).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })} · {p.readTime}</span>
        </div>

        <div className="prose-craft mt-8">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{p.content}</ReactMarkdown>
        </div>
      </article>
      <Footer />
    </div>
  );
}
