"use client";

// Stripe Embedded Checkout 완료 후 돌아오는 페이지(빌링 D46). 크레딧 적립은 웹훅이 비동기 처리하므로
// 여기선 "곧 반영" 안내만. 몇 초 뒤 Back to workspace 자동 복귀(마지막 프로젝트) + 수동 버튼도 제공.
import { track } from "@/lib/analytics";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

export default function BillingReturn() {
  const router = useRouter();

  useEffect(() => {
    track("purchase_completed");
    document.title = "Payment complete · pondas.ai";
    // /app 인덱스가 마지막으로 연 프로젝트로 복원한다. 잠깐 안내를 보여준 뒤 자동 이동.
    const t = setTimeout(() => router.replace("/app"), 2500);
    return () => clearTimeout(t);
  }, [router]);

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 px-6 text-center" style={{ background: "#C6C9BC" }}>
      <div className="font-baloo text-2xl font-extrabold text-ink">Payment complete 🎉</div>
      <p className="max-w-sm text-sm text-secondary">
        Your credits will land in the treasury shortly. Heading back to your workspace…
      </p>
      <Link href="/app" className="btn-pill btn-primary text-sm">
        Back to workspace
      </Link>
    </main>
  );
}
