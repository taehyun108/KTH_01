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

/** 국내 주요 도시 한글명 → 영문(GeoNames) 매핑. 국내여행 검색 지원. */
const KO_CITY_EN: Record<string, string> = {
  서울: "Seoul", 부산: "Busan", 인천: "Incheon", 대구: "Daegu", 대전: "Daejeon",
  광주: "Gwangju", 울산: "Ulsan", 세종: "Sejong", 수원: "Suwon", 제주: "Jeju City",
  제주도: "Jeju City", 제주시: "Jeju City", 서귀포: "Seogwipo", 경주: "Gyeongju", 전주: "Jeonju",
  강릉: "Gangneung", 속초: "Sokcho", 여수: "Yeosu", 순천: "Suncheon", 통영: "Tongyeong",
  포항: "Pohang", 안동: "Andong", 춘천: "Chuncheon", 가평: "Gapyeong", 양양: "Yangyang",
  창원: "Changwon", 목포: "Mokpo", 군산: "Gunsan", 태안: "Taean", 남해: "Namhae",
  거제: "Geoje", 평창: "Pyeongchang", 부천: "Bucheon", 고양: "Goyang", 용인: "Yongin",
};

/** 도시명(+선택 국가코드)으로 최대 인구 도시를 찾는다. 한글 국내 도시도 지원. */
export function offlineGeocode(city: string, countryCode?: string): OfflineContext | null {
  const raw = city.trim();
  // 한글 국내 도시면 영문으로 변환하고 국가를 KR 로 고정
  const koEn = KO_CITY_EN[raw] ?? KO_CITY_EN[raw.replace(/특별시|광역시|시$|도$/g, "")];
  const searchName = koEn ?? raw;
  const cc = koEn ? "KR" : countryCode;
  const q = normalize(searchName);
  let best: CityRecord | null = null;
  for (const c of DB) {
    if (cc && c.country !== cc) continue;
    if (normalize(c.name) !== q && normalize(c.altName ?? "") !== q) continue;
    if (!best || c.population > best.population) best = c;
  }
  // 폴백: 정확 일치 없으면 접두 일치("Jeju"→"Jeju City")로 최대 인구 도시.
  if (!best) {
    for (const c of DB) {
      if (cc && c.country !== cc) continue;
      if (!normalize(c.name).startsWith(q + " ")) continue;
      if (!best || c.population > best.population) best = c;
    }
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
    japan: "JP", korea: "KR", "south korea": "KR", 대한민국: "KR", 한국: "KR", 국내: "KR",
    일본: "JP", france: "FR", 프랑스: "FR", portugal: "PT", 포르투갈: "PT",
    vietnam: "VN", 베트남: "VN", "united states": "US", usa: "US", 미국: "US",
    thailand: "TH", 태국: "TH", spain: "ES", 스페인: "ES", italy: "IT", 이탈리아: "IT",
    taiwan: "TW", 대만: "TW", china: "CN", 중국: "CN",
  };
  return map[n];
}
