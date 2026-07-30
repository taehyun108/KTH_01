import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Tauri 개발 서버 설정
// ⚠️ 포터블 원칙: 포트는 .env 의 FRONTEND_PORT 와 맞춘다 (기본 5173)
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: 5173,
    strictPort: true,
  },
  build: {
    // 구형 사내 PC 브라우저 엔진도 고려해 보수적으로 설정
    target: "es2021",
    outDir: "dist",
    emptyOutDir: true,
  },
});
