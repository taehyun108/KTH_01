import type { GeoPoint, Poi, Restaurant } from "@/core/types/domains";
import type { VerifiedFact } from "@/core/types/verified-fact";
import type { Comparator, Observation } from "@/core/verification/observation";
import { verify } from "@/core/verification/verifier";
import { TOLERANCE } from "@/core/verification/tolerance";
import { haversineMeters } from "@/lib/geo";
import { timePrefFromCategories } from "./poi-select";

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
  /** 이 후보의 1차 출처(정직한 출처 표기). 기본 osm. */
  origin?: "osm" | "wiki";
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

/**
 * POI 후보를 VerifiedFact 로 구성. 각 후보의 1차 출처(origin)를 정직하게 표기하고,
 * 반대 출처(OSM↔Wikipedia)가 100m 내에 있으면 독립 교차검증으로 medium 승격.
 * @param osmPoints Overpass 로 확인된 지점들(위키 후보의 교차검증용)
 * @param wiki      Wikipedia 문서들(OSM 후보의 교차검증용)
 */
export function buildPoiFacts(
  seeds: PoiSeed[],
  osmPoints: GeoPoint[],
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
      ...(seed.categories ? { categories: seed.categories } : {}),
      time_pref: timePrefFromCategories(seed.categories),
    };
    const origin = seed.origin ?? "osm";
    const primary = origin === "wiki" ? WIKI_SOURCE : OSM_SOURCE;
    const obs: Observation<Poi>[] = [
      { value: poi, source: { ...primary, retrieved_at: iso }, pass: 1 },
    ];

    // 반대 출처로 교차검증(독립 도메인 → 일치 시 medium)
    if (origin === "osm") {
      const w = nearestWiki(wiki, seed.location);
      if (w) obs.push({ value: { name: seed.name, location: w.location }, source: { ...WIKI_SOURCE, retrieved_at: iso }, pass: 2 });
    } else {
      const p = nearestPoint(osmPoints, seed.location);
      if (p) obs.push({ value: { name: seed.name, location: p }, source: { ...OSM_SOURCE, retrieved_at: iso }, pass: 2 });
    }
    return verify<Poi>(obs, { comparator: cmp, tolerance: TOLERANCE.geo_distance_m });
  });
}

function nearestPoint(points: GeoPoint[], at: GeoPoint): GeoPoint | null {
  let best: GeoPoint | null = null;
  let bestD: number = TOLERANCE.geo_distance_m;
  for (const p of points) {
    const d = haversineMeters(p, at);
    if (d <= bestD) {
      bestD = d;
      best = p;
    }
  }
  return best;
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
