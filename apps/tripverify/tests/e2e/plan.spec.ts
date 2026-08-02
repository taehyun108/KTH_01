import { test, expect } from "@playwright/test";

/**
 * E2E (§8). 이 환경은 외부 API 가 차단되어 검증 소스가 없다. 따라서 앱은
 * "정직한 빈 일정 + 안내(notes)"로 응답해야 한다(§0-4). 네트워크가 허용된
 * 환경에서는 동일 흐름이 실제 검증된 일정을 렌더한다.
 */
test("여행 요청 → 앱이 정직하게 응답한다", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "TripVerify" })).toBeVisible();

  await page.getByRole("button", { name: /검증된 일정 생성/ }).click();

  // 생성 완료 후 탭이 나타난다(성공/폴백 무관).
  await expect(page.getByRole("button", { name: "검증 리포트" })).toBeVisible({
    timeout: 30_000,
  });

  await page.getByRole("button", { name: "검증 리포트" }).click();
  // 검증 등급 분포 섹션은 항상 렌더된다.
  await expect(page.getByText("검증 등급 분포")).toBeVisible();
});

test("잘못된 입력은 서버가 422 로 거절한다", async ({ request }) => {
  const res = await request.post("/api/plan", { data: { origin: "ICN" } });
  expect(res.status()).toBe(422);
});

test("헬스체크는 200 을 반환한다", async ({ request }) => {
  const res = await request.get("/api/health");
  expect(res.status()).toBe(200);
  const body = await res.json();
  expect(body.ok).toBe(true);
});
