// Playwright E2E(test-plan §2) — 로컬 스택(백엔드 uvicorn + 프론트 dev, 둘 다 E2E 모드) 전제.
// 실행: repo 루트의 scripts/e2e.sh (스택 기동 + 시드 + 스위트).
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 45_000,
  retries: 0,
  workers: 1, // 단일 시드 데이터 공유 — 병렬 금지.
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
});
