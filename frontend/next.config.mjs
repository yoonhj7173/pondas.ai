/** @type {import('next').NextConfig} */
const nextConfig = {
  // 과거 Pixi 캔버스 StrictMode 더블마운트 경합 때문에 껐음. 오피스는 DOM 카드로 전환(Pixi 제거)됐지만,
  // 재활성화가 SSE/맵 구독 등 다른 더블마운트를 건드릴 수 있어 보수적으로 유지.
  reactStrictMode: false,

  // 보안 헤더(감사 P2) — 클릭재킹/ MIME 스니핑 방지. 전체 CSP(script-src 등)는 Clerk/Stripe 로더와
  // 충돌 위험이 있어 프레이밍/스니핑/레퍼러만 강제(frame-ancestors 'none' = X-Frame-Options DENY의 현대판).
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Content-Security-Policy", value: "frame-ancestors 'none'" },
        ],
      },
    ];
  },
};

export default nextConfig;
