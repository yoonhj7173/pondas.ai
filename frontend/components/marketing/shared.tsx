// 마케팅 공유 컴포넌트 — 로고/Nav/Footer (핸드오프 marketing 토큰).
import Link from "next/link";

export function Logo({ sub }: { sub?: string }) {
  return (
    <Link href="/" className="flex items-center gap-2.5">
      <span className="flex h-9 w-9 items-center justify-center rounded-xl border-2 border-white font-baloo text-lg font-extrabold text-white"
        style={{ background: "linear-gradient(135deg,#67D2F2,#3FB4DC)", boxShadow: "0 4px 10px rgba(63,180,220,0.35)" }}>C</span>
      <span className="font-baloo text-xl font-extrabold text-navy">Craft</span>
      {sub && <span className="font-baloo text-xl font-bold text-muted">/ {sub}</span>}
    </Link>
  );
}

export function Nav({ blogSub }: { blogSub?: boolean }) {
  return (
    <nav className="sticky top-0 z-20 flex items-center justify-between border-b border-black/5 bg-[#FBFAF6]/90 px-6 py-4 backdrop-blur md:px-10">
      <Logo sub={blogSub ? "Blog" : undefined} />
      <div className="flex items-center gap-6 font-nunito text-sm font-bold text-ink-soft">
        {!blogSub && <Link href="/#how" className="hidden hover:text-ink sm:block">How it works</Link>}
        {!blogSub && <Link href="/blog" className="hidden hover:text-ink sm:block">Blog</Link>}
        <Link href="/onboarding" className="btn-pill btn-primary !py-2 text-sm">Get started</Link>
      </div>
    </nav>
  );
}

export function Footer() {
  return (
    <footer className="border-t border-black/5 bg-[#FBFAF6] px-6 py-10 md:px-10">
      <div className="mx-auto flex max-w-5xl flex-col items-center justify-between gap-4 sm:flex-row">
        <Logo />
        <div className="flex gap-6 font-nunito text-sm text-secondary">
          <Link href="/blog" className="hover:text-ink">Blog</Link>
          <Link href="/#" className="hover:text-ink">Privacy</Link>
          <Link href="/#" className="hover:text-ink">Terms</Link>
          <span className="text-muted">© {new Date().getFullYear()} Craft</span>
        </div>
      </div>
    </footer>
  );
}
