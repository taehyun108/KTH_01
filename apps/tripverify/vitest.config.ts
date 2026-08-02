import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
      // 'server-only' 가드는 RSC 전용이므로 노드 테스트에서는 스텁으로 대체.
      "server-only": fileURLToPath(new URL("./tests/mocks/server-only.ts", import.meta.url)),
    },
  },
  test: {
    environment: "node",
    include: ["tests/**/*.test.ts", "tests/**/*.test.tsx"],
    globals: true,
    // DB 테스트는 인메모리 SQLite 로 격리 실행.
    env: { DATABASE_URL: ":memory:" },
  },
});
