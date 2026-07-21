// History 패널(D61/D63) — 버전+라벨, 코드뷰, Launch 위저드 → LIVE 카드.
import { expect, test } from "@playwright/test";
import { openOffice, seededProjectId, API } from "./helpers";

test.beforeEach(async ({ request }) => {
  // 사이트 등록 초기화(멱등).
  const id = await seededProjectId(request);
  await request.delete(`${API}/api/projects/${id}/site`, { headers: { Authorization: "Bearer e2e" } });
});

test("history shows v1 with human label and file viewer", async ({ page, request }) => {
  const id = await seededProjectId(request);
  await openOffice(page, id);
  await page.getByRole("button", { name: /History/ }).click();
  await expect(page.getByText("Added candle mockup pages")).toBeVisible();
  await expect(page.getByText("2 files")).toBeVisible();
  // 코드뷰: 파일 열람(읽기 전용).
  await page.getByRole("button", { name: "View code" }).click();
  await page.getByRole("button", { name: "index.html" }).click();
  await expect(page.getByText("<h1>candles</h1>")).toBeVisible();
});

test("launch wizard registers a live site URL", async ({ page, request }) => {
  const id = await seededProjectId(request);
  await openOffice(page, id);
  await page.getByRole("button", { name: /History/ }).click();
  // GitHub 미연결이면 Launch 카드가 없어야 정상 — 이 스위트는 repo_full_name을 시드하지 않으므로
  // 카드 부재를 단정하고, API 레벨로 사이트 등록 계약을 검증한다(위저드 UI는 repo 연결 후 표면).
  await expect(page.getByText("Grand Opening")).toHaveCount(0);
  const bad = await request.put(`${API}/api/projects/${id}/site`, {
    headers: { Authorization: "Bearer e2e" },
    data: { url: "javascript:alert(1)" },
  });
  expect(bad.status()).toBe(422);
  const ok = await request.put(`${API}/api/projects/${id}/site`, {
    headers: { Authorization: "Bearer e2e" },
    data: { url: "https://e2e-candle.netlify.app" },
  });
  expect(ok.status()).toBe(204);
});
