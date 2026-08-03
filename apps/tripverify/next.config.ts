import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Docker 배포용 최소 번들.
  output: "standalone",
  // 네이티브/대용량 데이터 패키지는 서버 번들에서 외부화한다.
  serverExternalPackages: ["better-sqlite3", "date-holidays", "all-the-cities"],
};

export default nextConfig;
