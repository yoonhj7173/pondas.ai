import type { Metadata } from "next";
import Link from "next/link";
import { Nav, Footer } from "@/components/marketing/shared";

export const metadata: Metadata = {
  title: "Craft — Run your AI company like a tiny office sim",
  description:
    "Craft is an office-sim for solo founders: AI agents are workers in rooms, you steer them from one chat. Pick teams, wire the graph, dispatch work, and watch it get done — including real code, built and tested in a sandbox.",
  openGraph: {
    title: "Craft — Run your AI company like a tiny office sim",
    description: "A whole team. None of the hiring. AI agents you can see and steer.",
    type: "website",
    url: "/",
  },
  alternates: { canonical: "/" },
};

const softwareJsonLd = {
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  name: "Craft",
  applicationCategory: "BusinessApplication",
  operatingSystem: "Web",
  description:
    "An office-sim multi-agent orchestration app for solo founders — AI agents as workers in rooms, steered from one chat, including real code execution in sandboxes.",
  offers: { "@type": "Offer", price: "0", priceCurrency: "USD" },
};

export default function Landing() {
  return (
    <div className="min-h-screen bg-[#FBFAF6] font-nunito text-ink">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(softwareJsonLd) }} />
      <Nav />

      {/* Hero */}
      <section className="relative overflow-hidden border-b border-black/5"
        style={{ background: "linear-gradient(160deg,#DDE4D6,#C6C9BC), repeating-linear-gradient(0deg,transparent,transparent 41px,rgba(90,95,80,0.05) 42px)" }}>
        <div className="mx-auto grid max-w-6xl items-center gap-10 px-6 py-20 md:grid-cols-2 md:px-10">
          <div>
            <span className="inline-block rounded-pill bg-white/80 px-4 py-2 font-nunito text-sm font-extrabold text-navy shadow-sm">
              A whole team. None of the hiring.
            </span>
            <h1 className="mt-5 font-baloo text-5xl font-extrabold leading-[1.05] text-ink md:text-6xl">
              Run your AI company like a tiny office sim.
            </h1>
            <p className="mt-5 max-w-md text-lg text-secondary">
              Your agents are workers in rooms. Tell them what to do in one chat — they research, design, and build real software while you watch and steer.
            </p>
            <div className="mt-7 flex flex-col items-start gap-2">
              <Link href="/onboarding" className="btn-pill btn-confirm text-base">Start building →</Link>
              <span className="font-nunito text-sm text-muted">Free to try · sign in with Google</span>
            </div>
          </div>
          <OfficeVignette />
        </div>
      </section>

      {/* Answer cards (GEO-friendly Q&A) */}
      <section className="mx-auto max-w-6xl px-6 py-16 md:px-10">
        <div className="grid gap-5 md:grid-cols-3">
          <Answer icon="🏢" q="What is Craft?" a="A web app where you run a virtual company of AI agents, shown as a friendly office sim. Teams are rooms, agents are workers at desks, and you steer everything from one chat." />
          <Answer icon="🧑‍💻" q="Who is it for?" a="Solo founders building a product alone — who want planning, research, design, and development delegated to AI agents they can see, direct, and trust." />
          <Answer icon="⚡" q="Why is it different?" a="The dev team writes and runs real code in a sandbox — 'works as expected', not 'build passed'. You get working files, not just chat." />
        </div>
      </section>

      {/* How it works */}
      <section id="how" className="bg-[#F2EFE3] px-6 py-16 md:px-10">
        <div className="mx-auto max-w-6xl">
          <h2 className="text-center font-baloo text-3xl font-extrabold">How it works</h2>
          <div className="mt-10 grid gap-5 md:grid-cols-4">
            {[
              ["1", "Pick your teams", "Start from templates — Planning, Research, Design, Development."],
              ["2", "Wire the graph", "Connect agents: hand off output or loop a review until approved."],
              ["3", "Talk to dispatch", "Tell the orchestrator what you want in plain language."],
              ["4", "Watch & steer", "See status live, answer questions, stop or pause anytime."],
            ].map(([n, t, d]) => (
              <div key={n} className="rounded-card border-[3px] border-white bg-white/70 p-5">
                <span className="flex h-9 w-9 items-center justify-center rounded-full bg-primary-to font-baloo font-extrabold text-white">{n}</span>
                <div className="mt-3 font-baloo text-lg font-extrabold">{t}</div>
                <p className="mt-1 text-sm text-secondary">{d}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA band */}
      <section className="bg-navy px-6 py-20 text-center md:px-10">
        <h2 className="mx-auto max-w-2xl font-baloo text-4xl font-extrabold text-white">Got a to-do list? Hand it to the office.</h2>
        <Link href="/onboarding" className="btn-pill btn-confirm mt-7 inline-block text-base">Start building →</Link>
      </section>

      <Footer />
    </div>
  );
}

function Answer({ icon, q, a }: { icon: string; q: string; a: string }) {
  return (
    <div className="rounded-card border-[3px] border-white bg-white p-6 shadow-sm">
      <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-[#DCEEF8] text-xl">{icon}</div>
      <h3 className="mt-4 font-baloo text-xl font-extrabold">{q}</h3>
      <p className="mt-2 text-secondary">{a}</p>
    </div>
  );
}

function OfficeVignette() {
  // CSS로 그린 미니 오피스 카드(룸 + 사인 + 데스크). 실제 Pixi 미사용(마케팅 청크 깨끗).
  return (
    <div className="relative aspect-[4/3] rounded-card border-[3px] border-white shadow-card"
      style={{ background: "#C6C9BC", backgroundImage: "repeating-linear-gradient(0deg,transparent,transparent 21px,rgba(90,95,80,0.06) 22px),repeating-linear-gradient(90deg,transparent,transparent 21px,rgba(90,95,80,0.06) 22px)" }}>
      <div className="absolute inset-6 rounded-xl" style={{ background: "#F2EFE3" }}>
        <div className="absolute left-0 right-0 top-0 h-6 rounded-t-xl" style={{ background: "#D9CCAB" }} />
        <div className="absolute inset-x-4 bottom-4 top-9 rounded-lg" style={{ background: "#C8D6E4" }}>
          <span className="absolute left-1/2 top-2 -translate-x-1/2 rounded-md bg-navy px-3 py-1 font-baloo text-[11px] font-bold text-white">Development</span>
        </div>
      </div>
    </div>
  );
}
