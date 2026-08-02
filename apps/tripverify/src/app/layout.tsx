import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "TripVerify — 검증형 여행계획",
  description: "3중 교차검증을 통과한 사실 정보만 보여주는 여행계획 앱",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
