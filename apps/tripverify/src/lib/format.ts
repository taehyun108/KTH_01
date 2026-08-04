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

// ── 다국어 이름 표기 (한국어 · 영어 · 현지어) ─────────────────────────
export interface NamedPlace {
  name: string; // 현지(원어)
  name_en?: string;
  name_ko?: string;
}

/** 한국어 · 영어 · 현지어를 함께 표기(중복 제거). 예) "오사카성 · Osaka Castle · 大阪城". */
export function displayName(p: NamedPlace | null | undefined): string {
  if (!p) return "";
  const parts = [p.name_ko, p.name_en, p.name].filter(
    (v): v is string => !!v && v.trim().length > 0,
  );
  const seen = new Set<string>();
  const uniq = parts.filter((v) => (seen.has(v) ? false : (seen.add(v), true)));
  return uniq.join(" · ");
}

/** 지도/검색에 쓸 대표 이름 — 영어 우선, 없으면 현지어(정확도). */
export function searchName(p: NamedPlace | null | undefined): string {
  if (!p) return "";
  return p.name_en || p.name || p.name_ko || "";
}

// ── 외부 지도/검색 링크 (키 불필요, 무료) ─────────────────────────────
export interface LatLng {
  lat: number;
  lng: number;
}

/** 이름(+지역)으로 구글지도 검색 → 장소 카드(리뷰/영업시간)가 열린다. */
export function googleMapsPlace(name: string, area?: string): string {
  const q = area ? `${name} ${area}` : name;
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(q)}`;
}

/** 좌표 기반 정확한 핀. */
export function googleMapsCoord(loc: LatLng): string {
  return `https://www.google.com/maps/search/?api=1&query=${loc.lat}%2C${loc.lng}`;
}

/** 키 불필요 구글지도 iframe 임베드 URL. */
export function googleMapsEmbed(loc: LatLng, zoom = 12): string {
  return `https://www.google.com/maps?q=${loc.lat},${loc.lng}&z=${zoom}&output=embed`;
}

const GOOGLE_TRAVEL: Record<string, string> = {
  walk: "walking",
  transit: "transit",
  car: "driving",
};

/** 여러 경유지를 포함한 구글지도 길찾기 링크(하루 동선 전체). */
export function googleMapsDirections(stops: LatLng[], mode = "transit"): string {
  if (stops.length === 0) return "https://www.google.com/maps";
  const origin = stops[0]!;
  const dest = stops[stops.length - 1]!;
  const waypoints = stops
    .slice(1, -1)
    .map((s) => `${s.lat},${s.lng}`)
    .join("|");
  const travel = GOOGLE_TRAVEL[mode] ?? "transit";
  return (
    `https://www.google.com/maps/dir/?api=1&origin=${origin.lat},${origin.lng}` +
    `&destination=${dest.lat},${dest.lng}` +
    (waypoints ? `&waypoints=${encodeURIComponent(waypoints)}` : "") +
    `&travelmode=${travel}`
  );
}

/** 네이버 블로그 검색(최신 후기). */
export function naverBlogSearch(query: string): string {
  return `https://search.naver.com/search.naver?where=blog&query=${encodeURIComponent(query)}`;
}

/** 네이버 지도 검색. */
export function naverMapSearch(query: string): string {
  return `https://map.naver.com/p/search/${encodeURIComponent(query)}`;
}
