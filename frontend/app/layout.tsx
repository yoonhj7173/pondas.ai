import type { Metadata } from "next";
import { ClerkProvider } from "@clerk/nextjs";
import { Baloo_2, Nunito, JetBrains_Mono, Mulish, Bricolage_Grotesque } from "next/font/google";
import "./globals.css";

const baloo = Baloo_2({ subsets: ["latin"], weight: ["700", "800"], variable: "--font-baloo" });
const nunito = Nunito({ subsets: ["latin"], weight: ["600", "700", "800"], variable: "--font-nunito" });
const mono = JetBrains_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-mono" });
const mulish = Mulish({ subsets: ["latin"], weight: ["500", "700"], variable: "--font-mulish" });
const bricolage = Bricolage_Grotesque({ subsets: ["latin"], weight: ["700"], variable: "--font-bricolage" });

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000"),
  title: "Craft",
  description: "Run a virtual company of AI agents.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <ClerkProvider>
      <html lang="en" className={`${baloo.variable} ${nunito.variable} ${mono.variable} ${mulish.variable} ${bricolage.variable}`}>
        <body>{children}</body>
      </html>
    </ClerkProvider>
  );
}
