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
    <ClerkProvider
      // 로그인 모달 브랜드 스킨(QA-08) — Clerk 기본 무색 테마 대신 candy 토큰(pill 버튼·card 라운드).
      appearance={{
        variables: {
          colorPrimary: "#3fb4dc",
          colorText: "#2c2925",
          colorTextSecondary: "#5c574f",
          colorBackground: "#fdfcf8",
          borderRadius: "14px",
          fontFamily: "var(--font-nunito), sans-serif",
        },
        elements: {
          cardBox: "rounded-[24px] border-[2.5px] border-white shadow-[0_30px_70px_rgba(30,35,25,0.4)]",
          headerTitle: "font-extrabold",
          socialButtonsBlockButton: "rounded-full border-2 border-[#e6e7dd] font-bold",
          formButtonPrimary: "rounded-full font-extrabold",
          footer: "hidden", // "Secured by Clerk" 뱃지 숨김(브랜드 일관성)
        },
      }}
      // "Sign in to cursor-pm" 카피 교체(QA-08) — 내부 코드네임 노출 방지. Clerk 앱 이름 변경과 별개의 안전망.
      localization={{
        signIn: {
          start: {
            title: "Sign in to pondas.ai",
            subtitle: "Your AI office is waiting",
          },
        },
        signUp: {
          start: {
            title: "Join pondas.ai",
            subtitle: "Run a virtual company of AI agents",
          },
        },
      }}
    >
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
