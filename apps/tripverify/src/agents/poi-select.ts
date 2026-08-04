import type { GeoPoint } from "@/core/types/domains";
import type { PoiSeed, WikiArticle } from "./poi-build";
import { haversineMeters } from "@/lib/geo";
import { TOLERANCE } from "@/core/verification/tolerance";

/**
 * 여행 컨셉·스타일에 맞춰 POI 를 점수화·선별하는 순수 로직.
 * "하수도박물관" 같은 무명 장소를 걸러내고, 유명도(위키데이터/위키백과)와
 * 컨셉 카테고리 일치도로 상위 장소만 남긴다.
 */

export type Bucket =
  | "history"
  | "art"
  | "nature"
  | "activity"
  | "food"
  | "religious"
  | "family"
  | "view"
  | "shopping";

/** OSM 태그 → 카테고리 버킷 분류. */
export function classifyTags(tags: Record<string, string>): Bucket[] {
  const b = new Set<Bucket>();
  const t = tags["tourism"];
  const h = tags["historic"];
  const l = tags["leisure"];
  const a = tags["amenity"];
  if (h) {
    b.add("history");
    if (/temple|shrine|monastery|church|cathedral/.test(h)) b.add("religious");
  }
  if (t === "museum") b.add("history");
  if (t === "gallery" || t === "artwork") b.add("art");
  if (t === "viewpoint") b.add("view");
  if (t === "zoo" || t === "aquarium" || t === "theme_park") {
    b.add("activity");
    b.add("family");
  }
  if (l === "park" || l === "garden" || l === "nature_reserve") b.add("nature");
  if (a === "place_of_worship") b.add("religious");
  if (tags["shop"] === "mall" || t === "marketplace" || a === "marketplace") b.add("shopping");
  if (b.size === 0 && t === "attraction") b.add("view"); // 일반 명소
  return [...b];
}

/** 위키데이터/위키백과 태그가 있으면 '주목할 만한' 장소. */
export function notableFromTags(tags: Record<string, string>): boolean {
  return Boolean(tags["wikidata"] || tags["wikipedia"] || tags["heritage"]);
}

/** 컨셉 문구 + 스타일 → 선호 카테고리 버킷 집합. */
export function conceptBuckets(concept: string | undefined, styles: string[]): Set<Bucket> {
  const s = new Set<Bucket>();
  for (const st of styles) {
    if (st === "history") {
      s.add("history");
      s.add("religious");
    } else if (st === "food") {
      s.add("food");
    } else if (st === "relax") {
      s.add("nature");
      s.add("view");
    } else if (st === "activity") {
      s.add("activity");
      s.add("view");
    }
  }
  const t = (concept ?? "").toLowerCase();
  const rules: [RegExp, Bucket[]][] = [
    [/역사|유적|궁|성\b|palace|castle|history|heritage/, ["history"]],
    [/미식|맛집|먹거리|음식|food|시장|market/, ["food", "shopping"]],
    [/자연|공원|정원|숲|park|garden|nature/, ["nature"]],
    [/전망|뷰|야경|view|scenic/, ["view"]],
    [/예술|미술|갤러리|아트|art|gallery|감성/, ["art"]],
    [/사찰|절|신사|사원|종교|temple|shrine|temple/, ["religious"]],
    [/가족|아이|키즈|family|kids|동물원|zoo|아쿠아리움|aquarium|테마파크|theme/, ["family", "activity"]],
    [/쇼핑|shopping|mall|백화점/, ["shopping"]],
    [/액티비티|activity|체험/, ["activity"]],
  ];
  for (const [re, bs] of rules) if (re.test(t)) bs.forEach((x) => s.add(x));
  if (s.size === 0) {
    s.add("history");
    s.add("view");
    s.add("nature");
  }
  return s;
}

export interface SelectOpts {
  concept?: string;
  styles: string[];
  limit: number;
}

/** POI 점수 = 유명도 + 컨셉 카테고리 일치 + 정보 충실도. */
export function scoreSeed(seed: PoiSeed, pref: Set<Bucket>, wikiNear: boolean): number {
  let score = 0;
  if (seed.notable) score += 3;
  if (wikiNear) score += 2;
  const cats = seed.categories ?? [];
  const overlap = cats.filter((c) => pref.has(c as Bucket)).length;
  score += Math.min(overlap, 2) * 2;
  if (seed.opening_hours) score += 1; // 정보가 있는 곳 우대
  if (cats.length === 0 && !seed.notable) score -= 1; // 분류불가·무명 감점
  return score;
}

/** 컨셉/스타일/유명도로 상위 limit 개 POI 선별. */
export function selectPois(seeds: PoiSeed[], wiki: WikiArticle[], opts: SelectOpts): PoiSeed[] {
  const pref = conceptBuckets(opts.concept, opts.styles);
  const scored = seeds.map((seed) => ({
    seed,
    score: scoreSeed(seed, pref, hasNearWiki(wiki, seed.location)),
  }));
  scored.sort((a, b) => b.score - a.score);
  return scored
    .filter((x) => x.score > 0) // 무명·무관 장소 제외
    .slice(0, opts.limit)
    .map((x) => x.seed);
}

function hasNearWiki(wiki: WikiArticle[], at: GeoPoint): boolean {
  return wiki.some((w) => haversineMeters(w.location, at) <= TOLERANCE.geo_distance_m);
}
