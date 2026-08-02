import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // better-sqlite3 는 네이티브 모듈이므로 서버 번들에서 외부화한다.
  serverExternalPackages: ["better-sqlite3"],
};

export default nextConfig;
