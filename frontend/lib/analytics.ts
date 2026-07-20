// 분석(GA4 + Amplitude) — 쿠키 동의 기반(D46 Legal). 동의 전/키 없으면 전부 no-op.
// EU opt-in 준수: 동의("accepted") 전에는 어떤 분석 스크립트도 로드/추적하지 않는다.

export const GA_ID = process.env.NEXT_PUBLIC_GA_ID;
export const AMPLITUDE_KEY = process.env.NEXT_PUBLIC_AMPLITUDE_KEY;
// PostHog(D62) — MLP 퍼널의 1차 툴: visit→signup→project→first_task→result→deploy→purchase.
export const POSTHOG_KEY = process.env.NEXT_PUBLIC_POSTHOG_KEY;
export const POSTHOG_HOST = process.env.NEXT_PUBLIC_POSTHOG_HOST || "https://us.i.posthog.com";
// 하나라도 설정돼야 동의 배너를 띄운다(분석 미설정이면 쿠키 없음 → 배너 불필요).
export const ANALYTICS_CONFIGURED = Boolean(GA_ID || AMPLITUDE_KEY || POSTHOG_KEY);

const CONSENT_KEY = "pondas_consent";
export type Consent = "accepted" | "rejected" | null;

export function getConsent(): Consent {
  if (typeof window === "undefined") return null;
  const v = window.localStorage.getItem(CONSENT_KEY);
  return v === "accepted" || v === "rejected" ? v : null;
}

export function setConsent(c: "accepted" | "rejected"): void {
  try {
    window.localStorage.setItem(CONSENT_KEY, c);
  } catch {
    /* storage 차단 환경 무시 */
  }
}

export function resetConsent(): void {
  try {
    window.localStorage.removeItem(CONSENT_KEY);
  } catch {
    /* ignore */
  }
}

// 이벤트 추적 — 로드된 분석 도구로 전달. 미로드/미동의면 조용히 no-op.
export function track(event: string, props?: Record<string, unknown>): void {
  if (typeof window === "undefined") return;
  const w = window as unknown as {
    gtag?: (...a: unknown[]) => void;
    amplitude?: { track?: (e: string, p?: Record<string, unknown>) => void };
    posthog?: { capture?: (e: string, p?: Record<string, unknown>) => void };
  };
  try {
    w.gtag?.("event", event, props);
  } catch {
    /* ignore */
  }
  try {
    w.amplitude?.track?.(event, props);
  } catch {
    /* ignore */
  }
  try {
    w.posthog?.capture?.(event, props);
  } catch {
    /* ignore */
  }
}


// 프로젝트당 1회 이벤트(D58 퍼널) — first_task 같은 절벽 지표는 중복 없이 1번만.
export function trackOnce(key: string, event: string, props?: Record<string, unknown>): void {
  if (typeof window === "undefined") return;
  const k = `pondas_once_${key}`;
  try {
    if (window.localStorage.getItem(k)) return;
    window.localStorage.setItem(k, "1");
  } catch { /* private mode — 그냥 이벤트만 */ }
  track(event, props);
}
