import type { GeoPoint, Poi, Restaurant } from "@/core/types/domains";
import type { VerifiedFact } from "@/core/types/verified-fact";
import type { Comparator, Observation } from "@/core/verification/observation";
import { verify } from "@/core/verification/verifier";
import { TOLERANCE } from "@/core/verification/tolerance";
import { haversineMeters } from "@/lib/geo";

/**
 * OSM 발굴 결과(좌표 포함) → VerifiedFact 로 구성하는 순수 로직.
 * 이름 재조회 없이 발굴 시 받은 좌표를 그대로 쓰므로 언어 불일치 버그가 없다.
 * OSM 단일 출처면 low(표시됨), Wikipedia 가 100m 내에서 확인되면 medium 으로 승격.
 */

export interface PoiSeed {
  name: string; // 현지(원어)
  name_en?: string;
  name_ko?: string;
  location: GeoPoint;
  opening_hours?: (string | null)[];
  admission_fee_local?: number | null;
  /** 선별용 카테고리 버킷(poi-select). */
  categories?: string[];
  /** 위키데이터/위키백과 태그 보유(유명도). */
  notable?: boolean;
}
export interface RestaurantSeed {
  name: string;
  name_en?: string;
  name_ko?: string;
  location: GeoPoint;
  opening_hours?: (string | null)[];
  price_level?: 1 | 2 | 3 | 4;
  cuisine?: string;
}
export interface WikiArticle {
  title: string;
  location: GeoPoint;
}

const OSM_SOURCE = { name: "OpenStreetMap/Overpass", url: "https://overpass-api.de/", tier: 2 as const };
const WIKI_SOURCE = { name: "Wikipedia GeoSearch", url: "https://en.wikipedia.org/", tier: 2 as const };

function placeComparator<T extends { location: GeoPoint }>(): Comparator<T> {
  return {
    agree: (a, b) => haversineMeters(a.location, b.location) <= TOLERANCE.geo_distance_m,
    deviation: (a, b) => haversineMeters(a.location, b.location),
  };
}

/** OSM POI + (근접) Wikipedia 교차검증으로 VerifiedFact<Poi>[] 생성. */
export function buildPoiFacts(
  seeds: PoiSeed[],
  wiki: WikiArticle[],
  now: number = Date.now(),
): VerifiedFact<Poi>[] {
  const iso = new Date(now).toISOString();
  const cmp = placeComparator<Poi>();
  return seeds.map((seed) => {
    const poi: Poi = {
      name: seed.name,
      ...(seed.name_en ? { name_en: seed.name_en } : {}),
      ...(seed.name_ko ? { name_ko: seed.name_ko } : {}),
      location: seed.location,
      ...(seed.opening_hours ? { opening_hours: seed.opening_hours } : {}),
      ...(seed.admission_fee_local !== undefined ? { admission_fee_local: seed.admission_fee_local } : {}),
    };
    const obs: Observation<Poi>[] = [
      { value: poi, source: { ...OSM_SOURCE, retrieved_at: iso }, pass: 1 },
    ];
    const match = nearestWiki(wiki, seed.location);
    if (match) {
      obs.push({
        value: { name: seed.name, location: match.location },
        source: { ...WIKI_SOURCE, retrieved_at: iso },
        pass: 2,
      });
    }
    return verify<Poi>(obs, { comparator: cmp, tolerance: TOLERANCE.geo_distance_m });
  });
}

/** 식당은 대개 Wikipedia 에 없으므로 OSM 단일 출처(low, 표시됨)로 구성. */
export function buildRestaurantFacts(
  seeds: RestaurantSeed[],
  now: number = Date.now(),
): VerifiedFact<Restaurant>[] {
  const iso = new Date(now).toISOString();
  const cmp = placeComparator<Restaurant>();
  return seeds.map((seed) => {
    const r: Restaurant = {
      name: seed.name,
      ...(seed.name_en ? { name_en: seed.name_en } : {}),
      ...(seed.name_ko ? { name_ko: seed.name_ko } : {}),
      location: seed.location,
      ...(seed.opening_hours ? { opening_hours: seed.opening_hours } : {}),
      ...(seed.price_level !== undefined ? { price_level: seed.price_level } : {}),
      ...(seed.cuisine ? { cuisine: seed.cuisine } : {}),
    };
    return verify<Restaurant>(
      [{ value: r, source: { ...OSM_SOURCE, retrieved_at: iso }, pass: 1 }],
      { comparator: cmp, tolerance: TOLERANCE.geo_distance_m },
    );
  });
}

function nearestWiki(wiki: WikiArticle[], at: GeoPoint): WikiArticle | null {
  let best: WikiArticle | null = null;
  let bestD: number = TOLERANCE.geo_distance_m;
  for (const w of wiki) {
    const d = haversineMeters(w.location, at);
    if (d <= bestD) {
      bestD = d;
      best = w;
    }
  }
  return best;
}
