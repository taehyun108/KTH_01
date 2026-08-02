import "server-only";
import type { TripQuery, GeoContext } from "../types";
import { fetchJson } from "@/lib/http";

/**
 * 목적지 지리 컨텍스트 해석 (좌표/국가/통화). 키 불필요 소스.
 * Nominatim(OSM) 지오코딩 + REST Countries 통화. 실패 시 throw → 파이프라인이
 * notes 로 "조회 불가"를 표기한다(§0-4).
 */
export async function resolveContextLive(query: TripQuery): Promise<GeoContext> {
  const geo = await fetchJson<
    { lat: string; lon: string; address?: { country_code?: string } }[]
  >(
    `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(query.destination)}` +
      `&format=json&limit=1&addressdetails=1`,
  );
  const hit = geo[0];
  if (!hit) throw new Error(`목적지 지오코딩 실패: ${query.destination}`);
  const country_code = (hit.address?.country_code ?? "").toUpperCase();

  let currency_code = "USD";
  try {
    const cc = await fetchJson<{ currencies?: Record<string, unknown> }[]>(
      `https://restcountries.com/v3.1/alpha/${country_code}?fields=currencies`,
    );
    const code = Object.keys(cc[0]?.currencies ?? {})[0];
    if (code) currency_code = code;
  } catch {
    // 통화 조회 실패는 치명적이지 않음 — 기본값 유지
  }

  return {
    destination: query.destination,
    center: { lat: Number(hit.lat), lng: Number(hit.lon) },
    country_code,
    currency_code,
  };
}
