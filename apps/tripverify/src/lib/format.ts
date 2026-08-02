import type { Confidence } from "@/core/types/confidence";

export const CONFIDENCE_LABEL: Record<Confidence, string> = {
  high: "검증됨",
  medium: "부분검증",
  low: "확인 필요",
};

export const CONFIDENCE_EMOJI: Record<Confidence, string> = {
  high: "🟢",
  medium: "🟡",
  low: "🔴",
};

export function krw(n: number): string {
  return `₩${Math.round(n).toLocaleString("ko-KR")}`;
}

export function localAmount(n: number, code: string): string {
  return `${n.toLocaleString("ko-KR", { maximumFractionDigits: 2 })} ${code}`;
}

export function minutesLabel(min: number): string {
  if (min < 60) return `${min}분`;
  const h = Math.floor(min / 60);
  const m = min % 60;
  return m > 0 ? `${h}시간 ${m}분` : `${h}시간`;
}

export function isoToLocalTime(iso: string): string {
  const m = /T(\d{2}:\d{2})/.exec(iso);
  return m ? m[1]! : iso;
}

export function weekdayKo(w: number): string {
  return ["일", "월", "화", "수", "목", "금", "토"][w] ?? "";
}
