import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Docker 배포용 최소 번들.
  output: "standalone",
  // better-sqlite3 는 네이티브 모듈이므로 서버 번들에서 외부화한다.
  serverExternalPackages: ["better-sqlite3"],
};

export default nextConfig;
