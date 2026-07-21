// 온보딩 v2(D58/D59) — 6스텝 완주 → 오피스 진입 → 첫 목표가 챗에 프리필.
import { expect, test } from "@playwright/test";

test("onboarding walks 6 steps and prefills the first goal", async ({ page }) => {
  await page.goto("/onboarding?new=1");
  // E2E 모드: step 0(사인인) 자동 통과 → step 2(이름)부터.
  await page.getByPlaceholder("Jane").fill("Boss");
  await page.getByRole("button", { name: "Continue →" }).click();
  await page.getByPlaceholder("Acme Studio").fill("E2E Flow Co");
  await page.getByRole("button", { name: "Continue →" }).click();
  // 팀: Design + Development 선택.
  await page.getByRole("button", { name: /^Design/ }).click();
  await page.getByRole("button", { name: /^Development/ }).click();
  await page.getByRole("button", { name: "Continue →" }).click();
  // 컨텍스트 스킵.
  await page.getByRole("button", { name: "Continue →" }).click();
  // 첫 목표 카드 선택 → 개업.
  await page.getByRole("button", { name: /An online store/ }).click();
  await page.getByRole("button", { name: "Enter your office →" }).click();
  // 오피스: 챗 입력창에 목표 프리필(D58 — 절벽 해소의 핵심 단정).
  const chat = page.locator("textarea");
  await expect(chat).toHaveValue(/online store for handmade candles/i, { timeout: 20_000 });
  // 디오라마 룸 렌더.
  await expect(page.getByText("Development", { exact: true }).first()).toBeVisible();
});
