import type { Metadata } from "next";
import Link from "next/link";
import { Nav, Footer } from "@/components/marketing/shared";
import { allPosts, CATEGORY_CHIP } from "@/lib/blog";

export const metadata: Metadata = {
  title: "The Craft newsroom",
  description: "Notes from building a virtual company — product, agents, and the office sim. No fluff.",
  alternates: { canonical: "/blog" },
  openGraph: { title: "The Craft newsroom", type: "website", url: "/blog" },
};

function Chip({ category }: { category: string }) {
  const c = CATEGORY_CHIP[category] ?? { bg: "#ECE8DD", fg: "#6A6258" };
  return <span className="inline-block rounded-pill px-3 py-0.5 font-nunito text-xs font-bold" style={{ background: c.bg, color: c.fg }}>{category}</span>;
}

function Vignette({ tag }: { tag: string }) {
  return (
    <div className="relative aspect-[16/10] rounded-2xl border-[3px] border-white" style={{ background: "#C2DAC6", backgroundImage: "repeating-linear-gradient(0deg,transparent,transparent 21px,rgba(90,95,80,0.06) 22px),repeating-linear-gradient(90deg,transparent,transparent 21px,rgba(90,95,80,0.06) 22px)" }}>
      <div className="absolute left-1/2 top-1/2 h-16 w-24 -translate-x-1/2 -translate-y-1/2 rounded-lg border-2 border-white" style={{ background: "#EEE7D6" }}>
        <span className="absolute left-1/2 top-2 -translate-x-1/2 rounded bg-navy px-2 py-0.5 font-baloo text-[9px] font-bold text-white">{tag}</span>
      </div>
    </div>
  );
}

export default function BlogIndex() {
  const posts = allPosts();
  const [featured, ...rest] = posts;
  return (
    <div className="min-h-screen bg-[#FBFAF6] font-nunito text-ink">
      <Nav blogSub />
      <main className="mx-auto max-w-5xl px-6 py-14 md:px-10">
        <h1 className="font-baloo text-4xl font-extrabold md:text-5xl">The Craft newsroom</h1>
        <p className="mt-3 text-lg text-secondary">Notes from building a virtual company — product, agents, and the office sim. No fluff.</p>

        {featured && (
          <Link href={`/blog/${featured.slug}`} className="mt-10 grid items-center gap-6 md:grid-cols-2">
            <Vignette tag={featured.category.slice(0, 4)} />
            <div>
              <Chip category={featured.category} />
              <h2 className="mt-3 font-baloo text-2xl font-extrabold leading-tight md:text-3xl">{featured.title}</h2>
              <p className="mt-2 text-secondary">{featured.summary}</p>
              <p className="mt-3 font-mono text-xs text-muted">{featured.author} · {fmt(featured.date)} · {featured.readTime}</p>
            </div>
          </Link>
        )}

        <div className="mt-12 divide-y divide-black/5 border-t border-black/5">
          {rest.map((p) => (
            <Link key={p.slug} href={`/blog/${p.slug}`} className="flex flex-col gap-1 py-6 hover:opacity-80">
              <Chip category={p.category} />
              <h3 className="mt-1 font-baloo text-xl font-extrabold">{p.title}</h3>
              <p className="text-secondary">{p.summary}</p>
              <p className="mt-1 font-mono text-xs text-muted">{fmt(p.date)} · {p.readTime}</p>
            </Link>
          ))}
        </div>
      </main>
      <Footer />
    </div>
  );
}

function fmt(d: string): string {
  return new Date(d).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}
