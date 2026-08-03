import "server-only";
import cities from "all-the-cities";
import countryToCurrency from "country-to-currency";
import type { GeoContext, TripQuery } from "../types";
import type { GeoPoint } from "@/core/types/domains";

/**
 * 오프라인 지오코더 (§5 폴백, 무료·무네트워크).
 * GeoNames 기반 all-the-cities 데이터(번들)로 도시명→좌표/국가/통화를 해석한다.
 * 네트워크가 차단된 환경에서도 지도 중심·국가·통화코드가 동작하게 한다.
 * (환율 '값'은 여전히 온라인 소스 필요 — 여기선 통화 '코드'만 제공)
 */

interface CityRecord {
  name: string;
  altName?: string;
  country: string; // ISO2
  population: number;
  loc: { coordinates: [number, number] }; // [lng, lat]
}

const DB = cities as unknown as CityRecord[];

export interface OfflineContext {
  center: GeoPoint;
  country_code: string;
  currency_code: string;
}

/** 도시명(+선택 국가코드)으로 최대 인구 도시를 찾는다. */
export function offlineGeocode(city: string, countryCode?: string): OfflineContext | null {
  const q = normalize(city);
  let best: CityRecord | null = null;
  for (const c of DB) {
    if (countryCode && c.country !== countryCode) continue;
    if (normalize(c.name) !== q && normalize(c.altName ?? "") !== q) continue;
    if (!best || c.population > best.population) best = c;
  }
  if (!best) return null;
  const [lng, lat] = best.loc.coordinates;
  const currency =
    (countryToCurrency as Record<string, string>)[best.country] ?? "USD";
  return { center: { lat, lng }, country_code: best.country, currency_code: currency };
}

/** resolveContext 폴백: 온라인 지오코딩 실패 시 오프라인 데이터로 컨텍스트 구성. */
export async function resolveContextOffline(city: string, query: TripQuery): Promise<GeoContext> {
  const cc = query.country ? countryNameToIso(query.country) : undefined;
  const hit = offlineGeocode(city, cc);
  if (!hit) throw new Error(`오프라인 지오코딩 실패: ${city}`);
  return {
    destination: city,
    center: hit.center,
    country_code: hit.country_code,
    currency_code: hit.currency_code,
  };
}

function normalize(s: string): string {
  return s.trim().toLowerCase();
}

/** 흔한 국가명(영문)→ISO2 최소 매핑. 미매칭이면 undefined(전 국가 검색). */
function countryNameToIso(name: string): string | undefined {
  const n = normalize(name);
  const map: Record<string, string> = {
    japan: "JP", "korea": "KR", "south korea": "KR", "대한민국": "KR", 한국: "KR",
    일본: "JP", france: "FR", 프랑스: "FR", portugal: "PT", 포르투갈: "PT",
    vietnam: "VN", 베트남: "VN", "united states": "US", usa: "US", 미국: "US",
    thailand: "TH", 태국: "TH", spain: "ES", 스페인: "ES", italy: "IT", 이탈리아: "IT",
    taiwan: "TW", 대만: "TW", china: "CN", 중국: "CN",
  };
  return map[n];
}
