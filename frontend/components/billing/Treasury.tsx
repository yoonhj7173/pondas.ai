"use client";

// Treasury(빌링 D46) — 워크스페이스 HUD 타일 + "크레딧 충전" 모달(Embedded Checkout).
// 결제는 모달 안에서 완료되어 워크스페이스를 떠나지 않는다. 비용/토큰/모델은 노출 X(크레딧만).
import { useCallback, useEffect, useState } from "react";
import clsx from "clsx";
import { loadStripe } from "@stripe/stripe-js";
import { EmbeddedCheckoutProvider, EmbeddedCheckout } from "@stripe/react-stripe-js";
import { apiFetch } from "@/lib/api";
import { track } from "@/lib/analytics";

type Summary = { balance: number; plan: string; monthly_allowance: number };
type GetToken = () => Promise<string | null>;

const PK = process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY;
const stripePromise = PK ? loadStripe(PK) : null;

const PACKS = [
  { item: "pack_s", credits: 500, price: "$5" },
  { item: "pack_m", credits: 1500, price: "$13", best: true },
  { item: "pack_l", credits: 5000, price: "$40" },
];
const PLANS = [
  { item: "starter", name: "Starter", price: "$12/mo", note: "junior · standard" },
  { item: "pro", name: "Pro", price: "$40/mo", note: "+ senior (opus)" },
  { item: "studio", name: "Studio", price: "$200/mo", note: "bulk + concurrency" },
];

async function loadSummary(getToken: GetToken): Promise<Summary | null> {
  try {
    const t = await getToken();
    return await apiFetch<Summary>("/billing/summary", { token: t });
  } catch {
    return null;
  }
}

function Coin() {
  return (
    <span
      className="grid h-5 w-5 flex-none place-items-center rounded-full text-[11px] font-extrabold leading-none text-[#7a5410]"
      style={{ background: "radial-gradient(circle at 35% 30%,#fbdd8a,#f7b731)", border: "1.5px solid #d9990f" }}
    >
      ₵
    </span>
  );
}

/** TreasuryTile — 크레딧 잔액 다크 타일(우하단, 토큰 카운터 옆). 클릭 시 결제 모달. 위치는 부모(HUD)가 잡는다. */
export function TreasuryTile({ getToken, onOpen }: { getToken: GetToken; onOpen: () => void }) {
  const [s, setS] = useState<Summary | null>(null);
  useEffect(() => {
    loadSummary(getToken).then(setS);
  }, [getToken]);

  const bal = s?.balance ?? 0;
  const pct = s && s.monthly_allowance > 0 ? Math.min(100, Math.round((bal / s.monthly_allowance) * 100)) : null;

  return (
    <button
      onClick={onOpen}
      title="Credits — click to top up"
      className="w-48 rounded-2xl px-4 py-3 text-left text-ink shadow-card"
      style={{ background: "rgba(255,255,255,0.95)", border: "1px solid #E4DFEF", boxShadow: "0 10px 26px rgba(110,100,168,0.22)" }}
    >
      {/* '+' 버튼은 제거 — 타일 존재 자체로 크레딧 관리/결제 진입점임을 알 수 있다(2-2). */}
      <div className="flex items-center gap-2 font-baloo text-lg font-extrabold">
        <Coin /> <span>{bal.toLocaleString()}</span>
      </div>
      {pct !== null && (
        <>
          <div className="mt-2 text-[11px] font-semibold text-muted">{pct}% of monthly budget left</div>
          <div className="mt-2 h-1.5 overflow-hidden rounded bg-[#EFEDF5]">
            <div className="h-full rounded" style={{ width: `${pct}%`, background: "linear-gradient(90deg,#fbdd8a,#f7b731)" }} />
          </div>
        </>
      )}
    </button>
  );
}

/** BillingModal — 잔액 + 팩/플랜 선택 → Embedded Checkout(모달 내 결제). */
export function BillingModal({ getToken, paywall, onClose }: { getToken: GetToken; paywall?: boolean; onClose: () => void }) {
  const [s, setS] = useState<Summary | null>(null);
  const [item, setItem] = useState<string | null>(null);
  useEffect(() => {
    loadSummary(getToken).then(setS);
  }, [getToken]);

  // Esc로 닫기(BUG-3) — 다른 오버레이와 일관성. ✕/바깥클릭 외에 키보드로도 닫힌다.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // 구독 관리/해지 — Stripe Customer Portal로 이동(CA ARL click-to-cancel).
  async function openPortal() {
    try {
      const t = await getToken();
      const r = await apiFetch<{ url: string }>("/billing/portal", {
        method: "POST",
        token: t,
        body: JSON.stringify({ return_url: window.location.href }),
      });
      window.location.href = r.url;
    } catch {
      /* 결제 이력 없으면 portal 없음 */
    }
  }

  // 선택한 상품으로 Checkout 세션을 만들어 client_secret을 반환(Stripe가 호출).
  const fetchClientSecret = useCallback(async () => {
    const t = await getToken();
    const r = await apiFetch<{ client_secret: string }>("/billing/checkout", {
      method: "POST",
      token: t,
      body: JSON.stringify({
        item,
        return_url: `${window.location.origin}/billing/return?session_id={CHECKOUT_SESSION_ID}`,
      }),
    });
    return r.client_secret;
  }, [getToken, item]);

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center"
      style={{ background: "rgba(40,46,40,0.42)" }}
      onClick={onClose}
    >
      <div
        className="w-[440px] max-w-[92vw] overflow-hidden rounded-3xl bg-[#fdfdfb] shadow-card"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="relative border-b border-[#ece8dc] p-5">
          <button onClick={onClose} className="absolute right-4 top-4 grid h-8 w-8 place-items-center rounded-lg bg-[#efeadd] text-secondary">
            ✕
          </button>
          <div className="flex items-center gap-2 text-sm font-bold text-secondary">
            <Coin /> Treasury
          </div>
          <div className="mt-2 font-baloo text-3xl font-extrabold tracking-tight">
            {(s?.balance ?? 0).toLocaleString()} <span className="text-sm font-bold text-muted">credits</span>
          </div>
          {s?.plan && s.plan !== "free" && <div className="mt-1 text-xs font-semibold text-muted">Plan: {s.plan}</div>}
        </div>

        {/* 소진으로 자동 노출된 경우(D46 페이월) — 왜 떴는지 + 다음 행동을 명확히. */}
        {paywall && (
          <div className="border-b border-[#f0e2c8] bg-[#fff7e6] px-5 py-3 text-sm font-semibold text-[#8a5a08]">
            Out of credits — top up to keep your team working.
          </div>
        )}

        <div className="p-5">
          {item ? (
            <>
              <button onClick={() => setItem(null)} className="mb-3 text-xs font-bold text-primary-to">
                ← back
              </button>
              {stripePromise ? (
                <EmbeddedCheckoutProvider key={item} stripe={stripePromise} options={{ fetchClientSecret }}>
                  <EmbeddedCheckout />
                </EmbeddedCheckoutProvider>
              ) : (
                <div className="text-sm text-muted">
                  Payments not configured yet (NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY).
                </div>
              )}
            </>
          ) : (
            <>
              <div className="mb-3 text-[11px] font-extrabold uppercase tracking-wide text-muted">Add credits</div>
              <div className="grid grid-cols-3 gap-2.5">
                {PACKS.map((p) => (
                  <button
                    key={p.item}
                    onClick={() => {
                      track("checkout_started", { item: p.item });
                      setItem(p.item);
                    }}
                    className={clsx(
                      "relative rounded-2xl border-2 bg-[#fffdf9] p-4 text-center transition-colors",
                      p.best ? "border-primary-to" : "border-[#e8e2d3] hover:border-[#cfe9f3]",
                    )}
                  >
                    {p.best && (
                      <span className="absolute -top-2.5 left-1/2 -translate-x-1/2 rounded-full border-[1.5px] border-white bg-[#f7b731] px-2 py-0.5 text-[9px] font-extrabold text-[#5b3d0c]">
                        BEST
                      </span>
                    )}
                    <div className="font-baloo text-base font-extrabold">+{p.credits.toLocaleString()}</div>
                    <div className="text-xs font-bold text-secondary">{p.price}</div>
                  </button>
                ))}
              </div>

              <div className="mt-4 border-t border-[#ece8dc] pt-4">
                <div className="mb-2 text-[11px] font-extrabold uppercase tracking-wide text-muted">Or upgrade your plan</div>
                <div className="flex flex-col gap-2">
                  {PLANS.map((pl) => (
                    <button
                      key={pl.item}
                      onClick={() => {
                        track("checkout_started", { item: pl.item });
                        setItem(pl.item);
                      }}
                      className="flex items-center justify-between rounded-xl border border-[#e8e2d3] bg-white px-3 py-2 text-left transition-colors hover:border-[#cfe9f3]"
                    >
                      <span>
                        <b className="font-baloo">{pl.name}</b> <span className="text-xs text-muted">· {pl.note}</span>
                      </span>
                      <span className="text-sm font-bold text-secondary">{pl.price}</span>
                    </button>
                  ))}
                </div>
              </div>
            </>
          )}

          {/* 구독 관리/해지 진입(CA ARL click-to-cancel) — 구독 중일 때. */}
          {!item && s?.plan && s.plan !== "free" && (
            <button
              onClick={openPortal}
              className="mt-4 w-full rounded-xl border border-[#e8e2d3] bg-white py-2 text-sm font-bold text-secondary transition-colors hover:border-[#cfe9f3]"
            >
              Manage subscription &amp; cancel
            </button>
          )}

          {/* 결제 시점 고지(CA ARL + Stripe 정책 링크). 구독은 취소 전까지 자동갱신. */}
          <p className="mt-4 border-t border-[#ece8dc] pt-3 text-[11px] leading-relaxed text-muted">
            Subscriptions renew automatically until you cancel; cancel anytime in billing settings. By continuing
            you agree to our{" "}
            <a href="/terms" target="_blank" className="font-bold text-primary-to">Terms</a> and{" "}
            <a href="/refunds" target="_blank" className="font-bold text-primary-to">Refund Policy</a>.
          </p>
        </div>
      </div>
    </div>
  );
}
