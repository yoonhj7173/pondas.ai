import type { MetadataRoute } from "next";

// 웹 앱 매니페스트 — 모바일 "홈 화면에 추가" + 브라우저 테마색. Next가 /manifest.webmanifest로 서빙하고
// <link rel="manifest">를 자동 주입. PWA 풀스택은 아니고 기본 메타/설치성만 채운다.
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "pondas.ai",
    short_name: "pondas",
    description: "Run a virtual company of AI agents.",
    start_url: "/",
    display: "standalone",
    background_color: "#FBFAF6",
    theme_color: "#1f2a44",
    icons: [{ src: "/icon.png", sizes: "any", type: "image/png" }],
  };
}
