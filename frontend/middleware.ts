import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";
import { NextResponse } from "next/server";

// /app/*는 로그인 필수(D24). 미인증이면 온보딩으로 돌려보냄 — 거기서 앱 내 구글 모달로 로그인.
// /onboarding 자체는 공개(모달이 첫 스텝에서 로그인 강제). 마케팅(/, /blog)도 공개. E2E는 우회.
const isApp = createRouteMatcher(["/app(.*)"]);

export default clerkMiddleware(async (auth, req) => {
  if (process.env.NEXT_PUBLIC_E2E === "1" && process.env.NODE_ENV !== "production") return; // dev 빌드에서만 게이트 우회.
  if (isApp(req)) {
    const { userId } = await auth();
    if (!userId) return NextResponse.redirect(new URL("/onboarding", req.url));
  }
});

export const config = {
  matcher: ["/((?!_next|.*\\..*).*)", "/(api|trpc)(.*)"],
};
