import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Docker 배포는 standalone 번들, Vercel 은 자체 빌드 출력을 쓰므로 제외.
  ...(process.env.VERCEL ? {} : { output: "standalone" as const }),
  // 네이티브/대용량 데이터 패키지는 서버 번들에서 외부화한다.
  serverExternalPackages: ["better-sqlite3", "date-holidays", "all-the-cities"],
};

export default nextConfig;
