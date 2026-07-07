import type { Metadata } from "next";
import { ClerkProvider } from "@clerk/nextjs";
import { Baloo_2, Nunito, JetBrains_Mono, Mulish, Bricolage_Grotesque } from "next/font/google";
import "./globals.css";
import Analytics from "@/components/analytics/Analytics";

const baloo = Baloo_2({ subsets: ["latin"], weight: ["700", "800"], variable: "--font-baloo" });
const nunito = Nunito({ subsets: ["latin"], weight: ["600", "700", "800"], variable: "--font-nunito" });
const mono = JetBrains_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-mono" });
const mulish = Mulish({ subsets: ["latin"], weight: ["500", "700"], variable: "--font-mulish" });
const bricolage = Bricolage_Grotesque({ subsets: ["latin"], weight: ["700"], variable: "--font-bricolage" });

const SITE = (process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000").replace(/\/$/, "");

// 브랜드 엔티티 그래프 — Organization(회사)+WebSite(사이트)를 모든 페이지에 심는다.
// 구글이 브랜드/사이트를 하나의 엔티티로 인식(지식패널·sitelinks 신호). WebSite.publisher가
// Organization을 @id로 참조해 둘을 연결. 개별 페이지 스키마(랜딩 SoftwareApplication, 블로그
// Article)는 여기 Organization을 publisher로 재참조한다.
const orgJsonLd = {
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "Organization",
      "@id": `${SITE}/#organization`,
      name: "pondas.ai",
      url: SITE,
      logo: `${SITE}/icon.png`,
    },
    {
      "@type": "WebSite",
      "@id": `${SITE}/#website`,
      name: "pondas.ai",
      url: SITE,
      publisher: { "@id": `${SITE}/#organization` },
    },
  ],
};

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000"),
  title: { default: "pondas.ai", template: "%s · pondas.ai" },
  description: "Run a virtual company of AI agents.",
  verification: { google: "SOUqe-MO6bSO-4pNc1D4FcdW0UJhGR8AjlPHW_OtwDs" },
  openGraph: {
    title: "pondas.ai",
    description: "Run a virtual company of AI agents.",
    siteName: "pondas.ai",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "pondas.ai",
    description: "Run a virtual company of AI agents.",
  },
};

/**
 * RootLayout — 모든 페이지를 감싸는 최상위 껍데기. 폰트와 로그인 컨텍스트를 앱 전체에 깐다.
 *
 * 무슨 일을 하나: 공통 폰트 변수를 <html>에 걸고, 전체를 <ClerkProvider>로 감싼다.
 *   ClerkProvider = 로그인 상태를 앱 어디서나 쓸 수 있게 해주는 인증 공급자(Spring Security의
 *   SecurityContext가 앱 전역에 깔리는 것과 비슷). 덕분에 어느 컴포넌트든 useAuth로 토큰을 얻는다.
 * 누가 부르나: Next.js가 모든 라우트를 자동으로 이 레이아웃으로 감싼다(App Router 규약).
 * 연결: 여기서 깔린 토큰을 실제로 쓰는 곳 → 각 페이지의 useAuth() → apiFetch (frontend/lib/api.ts).
 */
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <ClerkProvider>
      <html lang="en" className={`${baloo.variable} ${nunito.variable} ${mono.variable} ${mulish.variable} ${bricolage.variable}`}>
        <body>
          <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(orgJsonLd) }} />
          {children}
          <Analytics />
        </body>
      </html>
    </ClerkProvider>
  );
}
