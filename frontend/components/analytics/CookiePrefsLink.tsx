"use client";

// 쿠키 동의 재설정 링크 — 동의 철회/변경(GDPR easy-withdraw). 배너를 다시 띄운다.
import { resetConsent } from "@/lib/analytics";

export function CookiePrefsLink({ className }: { className?: string }) {
  return (
    <button
      type="button"
      onClick={() => {
        resetConsent();
        window.dispatchEvent(new Event("pondas:cookie-prefs"));
      }}
      className={className}
    >
      Cookie preferences
    </button>
  );
}
