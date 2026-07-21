// 공용 헬퍼 — E2E 모드(NEXT_PUBLIC_E2E=1)의 apiFetch는 토큰 "e2e"를 쓰고 백엔드는
// E2E_AUTH_BYPASS로 e2e_user에 매핑한다. 시드 프로젝트는 이름으로 찾는다.
import { APIRequestContext, Page, expect } from "@playwright/test";

export const API = process.env.E2E_API_URL ?? "http://localhost:8000";

export async function seededProjectId(request: APIRequestContext): Promise<string> {
  const res = await request.get(`${API}/api/projects`, {
    headers: { Authorization: "Bearer e2e" },
  });
  expect(res.ok()).toBeTruthy();
  const projects = (await res.json()) as { id: string; name: string }[];
  const p = projects.find((x) => x.name === "E2E Candle");
  if (!p) throw new Error("seed missing — run scripts/seed_e2e_fixture.py");
  return p.id;
}

export async function openOffice(page: Page, projectId: string) {
  // 온보딩 투어 모달이 상호작용을 가로막지 않게 사전 dismiss.
  await page.addInitScript(() => localStorage.setItem("pondas_tour_v1", "done"));
  await page.goto(`/app/${projectId}`);
  await expect(page.getByText("Design", { exact: true }).first()).toBeVisible({ timeout: 15_000 });
}
