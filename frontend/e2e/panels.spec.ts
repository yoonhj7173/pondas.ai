// 에이전트 패널(item 38) — failed 태스크에 Fix it + Retry, done 결과 인패널 렌더.
import { expect, test } from "@playwright/test";
import { openOffice, seededProjectId } from "./helpers";

test("failed agent panel offers Fix it and Retry", async ({ page, request }) => {
  const id = await seededProjectId(request);
  await openOffice(page, id);
  // 디자이너 아바타 클릭 → 패널. (시드 최신 태스크 = failed)
  await page.getByTitle("Product Designer").click();
  await expect(page.getByText("Simulated failure for E2E")).toBeVisible();
  await expect(page.getByRole("button", { name: /Fix it/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /Retry from scratch/ })).toBeVisible();
});
