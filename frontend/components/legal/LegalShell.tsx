// 법률 문서(ToS/Privacy/Refunds) 공용 셸 — 헤더 + prose 컨테이너(D46 Legal).
import Link from "next/link";
import type { ReactNode } from "react";

export function LegalShell({ title, updated, children }: { title: string; updated: string; children: ReactNode }) {
  return (
    <main className="min-h-screen bg-[#FBFAF6] font-nunito text-ink">
      <div className="mx-auto max-w-3xl px-6 py-14">
        <Link href="/" className="text-sm font-extrabold text-primary-to hover:underline">
          ← pondas
        </Link>
        <h1 className="mt-4 font-baloo text-3xl font-extrabold tracking-tight">{title}</h1>
        <p className="mt-1 text-sm text-muted">Last updated: {updated}</p>
        <div className="legal-prose mt-8">{children}</div>
        <div className="mt-12 flex gap-5 border-t border-black/5 pt-6 text-sm text-secondary">
          <Link href="/terms" className="hover:text-ink">Terms</Link>
          <Link href="/privacy" className="hover:text-ink">Privacy</Link>
          <Link href="/refunds" className="hover:text-ink">Refunds</Link>
        </div>
      </div>
    </main>
  );
}
