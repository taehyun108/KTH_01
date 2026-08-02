import { defineConfig, devices } from "@playwright/test";
import { existsSync, readdirSync } from "node:fs";
import { join } from "node:path";

/**
 * 이 환경에는 브라우저가 /opt/pw-browsers 에 사전설치돼 있고 버전 핀이 다를 수
 * 있어, playwright install 대신 설치된 chrome 실행파일을 직접 지정한다.
 */
function findChrome(): string | undefined {
  const base = process.env.PLAYWRIGHT_BROWSERS_PATH ?? "/opt/pw-browsers";
  if (!existsSync(base)) return undefined;
  const dir = readdirSync(base).find((d) => d.startsWith("chromium-"));
  if (!dir) return undefined;
  const bin = join(base, dir, "chrome-linux", "chrome");
  return existsSync(bin) ? bin : undefined;
}
const chromePath = findChrome();

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: "list",
  use: {
    baseURL: "http://localhost:3000",
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        ...(chromePath ? { launchOptions: { executablePath: chromePath } } : {}),
      },
    },
  ],
  webServer: {
    command: "pnpm dev",
    url: "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
