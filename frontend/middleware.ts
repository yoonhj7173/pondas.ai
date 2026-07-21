import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";
import { NextResponse } from "next/server";

// /app/*는 로그인 필수(D24). 미인증이면 온보딩으로 돌려보냄 — 거기서 앱 내 구글 모달로 로그인.
// /onboarding 자체는 공개(모달이 첫 스텝에서 로그인 강제). 마케팅(/, /blog)도 공개. E2E는 우회.
// 추가로, 이미 로그인한 사용자가 루트('/')에 오면 마케팅 랜딩 대신 워크스페이스로 바로 보낸다.
const isApp = createRouteMatcher(["/app(.*)"]);

// E2E(dev 전용): clerkMiddleware "래퍼 자체"를 우회해야 한다 — 핸들러 안의 early-return으로는
// 래퍼의 authenticateRequest(핸드셰이크)가 먼저 돌아 CI(시크릿 키 없음)에서 전 페이지가
// Server Error로 죽는다(실사고 2026-07-21). prod 빌드에선 E2E 플래그가 강제 off라 안전.
const E2E = process.env.NEXT_PUBLIC_E2E === "1" && process.env.NODE_ENV !== "production";

const clerkGate = clerkMiddleware(async (auth, req) => {
  if (isApp(req)) {
    const { userId } = await auth();
    if (!userId) return NextResponse.redirect(new URL("/onboarding", req.url));
    return;
  }
  // 로그인 상태로 루트에 진입하면 워크스페이스로(비로그인/크롤러는 그대로 랜딩을 본다 → SEO 유지).
  if (req.nextUrl.pathname === "/") {
    const { userId } = await auth();
    if (userId) return NextResponse.redirect(new URL("/app", req.url));
  }
});

export default E2E ? () => NextResponse.next() : clerkGate;

export const config = {
  matcher: ["/((?!_next|.*\\..*).*)", "/(api|trpc)(.*)"],
};
