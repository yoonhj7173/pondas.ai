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

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000"),
  title: { default: "pondas.ai", template: "%s · pondas.ai" },
  description: "Run a virtual company of AI agents.",
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
          {children}
          <Analytics />
        </body>
      </html>
    </ClerkProvider>
  );
}
