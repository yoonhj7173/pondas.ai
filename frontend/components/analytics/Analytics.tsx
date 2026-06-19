"use client";

// 분석 로더 + 쿠키 동의 배너(D46 Legal). 동의("accepted") + env키가 있을 때만 GA4/Amplitude 로드.
// EU opt-in 준수: 동의 전엔 아무 추적도 안 함. 거부/미동의 시 분석 스크립트 미로드.
import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import Script from "next/script";
import Link from "next/link";
import {
  GA_ID,
  AMPLITUDE_KEY,
  ANALYTICS_CONFIGURED,
  getConsent,
  setConsent,
  track,
  type Consent,
} from "@/lib/analytics";

export default function Analytics() {
  const [consent, setConsentState] = useState<Consent>(null);
  const [ready, setReady] = useState(false);
  const pathname = usePathname();

  useEffect(() => {
    setConsentState(getConsent());
    setReady(true);
    const onReset = () => setConsentState(null);
    window.addEventListener("pondas:cookie-prefs", onReset);
    return () => window.removeEventListener("pondas:cookie-prefs", onReset);
  }, []);

  // Amplitude는 동의 후 동적 로드.
  useEffect(() => {
    const key = AMPLITUDE_KEY;
    if (consent !== "accepted" || !key) return;
    let cancelled = false;
    import("@amplitude/analytics-browser").then((amp) => {
      if (cancelled) return;
      amp.init(key, { defaultTracking: true });
      (window as unknown as { amplitude?: unknown }).amplitude = amp;
    });
    return () => {
      cancelled = true;
    };
  }, [consent]);

  // SPA 라우트 변경 시 페이지뷰(동의 후).
  useEffect(() => {
    if (consent !== "accepted") return;
    track("page_view", { path: pathname });
  }, [pathname, consent]);

  const decide = (c: "accepted" | "rejected") => {
    setConsent(c);
    setConsentState(c);
  };

  return (
    <>
      {consent === "accepted" && GA_ID && (
        <>
          <Script src={`https://www.googletagmanager.com/gtag/js?id=${GA_ID}`} strategy="afterInteractive" />
          <Script id="ga-init" strategy="afterInteractive">
            {`window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}window.gtag=gtag;gtag('js',new Date());gtag('config','${GA_ID}');`}
          </Script>
        </>
      )}

      {ready && consent === null && ANALYTICS_CONFIGURED && (
        <div className="fixed inset-x-3 bottom-3 z-[60] mx-auto max-w-md rounded-2xl border border-[#e8e2d3] bg-white p-4 shadow-card sm:inset-x-auto sm:right-5">
          <p className="font-nunito text-sm text-secondary">
            We use cookies for analytics to improve pondas. You can accept or decline.{" "}
            <Link href="/privacy" className="font-bold text-primary-to">
              Privacy
            </Link>
          </p>
          <div className="mt-3 flex gap-2">
            <button onClick={() => decide("accepted")} className="btn-pill btn-primary flex-1 text-sm">
              Accept
            </button>
            <button
              onClick={() => decide("rejected")}
              className="flex-1 rounded-pill border-[2.5px] border-[#e8e2d3] bg-white py-2 font-baloo text-sm font-extrabold text-secondary"
            >
              Decline
            </button>
          </div>
        </div>
      )}
    </>
  );
}
