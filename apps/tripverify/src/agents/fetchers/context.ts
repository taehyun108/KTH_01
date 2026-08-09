import "server-only";
import type { TripQuery, GeoContext } from "../types";
import { fetchJson } from "@/lib/http";

/**
 * 목적지 지리 컨텍스트 해석 (좌표/국가/통화). 키 불필요 소스.
 * Nominatim(OSM) 지오코딩 + REST Countries 통화. 실패 시 throw → 파이프라인이
 * notes 로 "조회 불가"를 표기한다(§0-4).
 */
export async function resolveContextLive(city: string, query: TripQuery): Promise<GeoContext> {
  const q = query.country ? `${city}, ${query.country}` : city;
  // Nominatim 은 클라우드 IP 를 자주 차단/지연시킨다. 짧은 타임아웃(4s)으로 빠르게
  // 실패시켜 오프라인 지오코더 폴백이 제때 동작하도록 한다(빈 일정 방지).
  const geo = await fetchJson<
    { lat: string; lon: string; address?: { country_code?: string } }[]
  >(
    `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(q)}` +
      `&format=json&limit=1&addressdetails=1`,
    { timeoutMs: 4_000 },
  );
  const hit = geo[0];
  if (!hit) throw new Error(`목적지 지오코딩 실패: ${city}`);
  const country_code = (hit.address?.country_code ?? "").toUpperCase();

  let currency_code = "USD";
  try {
    const cc = await fetchJson<{ currencies?: Record<string, unknown> }[]>(
      `https://restcountries.com/v3.1/alpha/${country_code}?fields=currencies`,
      { timeoutMs: 3_000 }, // 통화 조회가 컨텍스트 예산(8s)을 넘기지 않도록 상한
    );
    const code = Object.keys(cc[0]?.currencies ?? {})[0];
    if (code) currency_code = code;
  } catch {
    // 통화 조회 실패는 치명적이지 않음 — 기본값 유지
  }

  return {
    destination: city,
    center: { lat: Number(hit.lat), lng: Number(hit.lon) },
    country_code,
    currency_code,
  };
}
