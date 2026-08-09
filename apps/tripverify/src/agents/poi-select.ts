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

export const BUCKET_LABEL: Record<Bucket, string> = {
  history: "역사",
  art: "예술",
  nature: "자연",
  activity: "액티비티",
  food: "미식",
  religious: "사찰·종교",
  family: "가족",
  view: "전망",
  shopping: "쇼핑",
};

/** 컨셉/스타일에서 강조된 테마(한글 라벨)를 도출한다. UI 설명용. */
export function conceptThemes(concept: string | undefined, styles: string[]): string[] {
  return [...conceptBuckets(concept, styles)].map((b) => BUCKET_LABEL[b]);
}

/** 감수성: 카테고리로 방문 권장 시간대 도출. 전망(타워/전망대)=야경(저녁). */
export function timePrefFromCategories(cats: string[] | undefined): "morning" | "day" | "evening" {
  const c = cats ?? [];
  if (c.includes("view")) return "evening"; // 타워·전망대는 야경이 백미
  if (c.includes("shopping")) return "morning"; // 시장은 오전이 활기
  return "day";
}

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
  if (seed.on_osm) score += 3; // OSM 존재 = 현존·구글지도 검색 가능성 → 강하게 우대
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

// ── Wikipedia 기반 POI 후보(클라우드에서 안정적인 주 소스) ─────────────
/** 관광지가 아닌 위키 문서(역/학교/관공서/기업 등) 배제. */
const WIKI_BLOCK =
  /station|駅|\bline\b|철도|\b역\b|university|college|\bschool\b|학교|hospital|병원|clinic|prefecture|\bward\b|district|-ku\b|구청|정류장|airport|공항|highway|expressway|국도|\briver\b|\b강\b|election|festival\s|배구|축구|野球|celebrity|singer|band|manga|anime|company|corporation|주식회사|\blist of|administration|\bagency\b|ministry|government|headquarters|bureau|\bauthority\b|commission|council|department of|embassy|consulate|\bbank\b|association|federation|institute of|research center|office\b|법원|court\b|경찰|police|city hall|시청|군청|도청/i;

/** 위키 제목에서 카테고리 추론(영어/일본식 로마자/현지 키워드). */
export function inferCategoriesFromTitle(title: string): Bucket[] {
  const b = new Set<Bucket>();
  const t = title.toLowerCase();
  // 성: castle, -jo, 城
  if (/castle|城|palace|궁|\bfort\b|[-\s]jō?\b|[-\s]jo\b/.test(t)) b.add("history");
  // 사찰/신사: temple, -ji/-dera/-tera(절), shrine, -taisha/-jinja/-jingu/-gu(신사)
  if (/temple|shrine|寺|神社|사원|사찰|신사|[-\s](ji|dera|tera)\b|(taisha|jinja|jingu|jingū)\b/.test(t))
    b.add("religious");
  if (/museum|博物館|박물관|미술관/.test(t)) b.add("history");
  if (/gallery|\bart\b|미술/.test(t)) b.add("art");
  if (/park|公園|garden|庭園|정원|공원|[-\s]koen\b|[-\s]kōen\b/.test(t)) b.add("nature");
  if (/tower|타워|observator|전망|展望|\bsky\b/.test(t)) b.add("view");
  if (/zoo|動物園|aquarium|水族館|동물원|수족관/.test(t)) {
    b.add("family");
    b.add("activity");
  }
  if (/market|市場|시장|\bmall\b|백화점|shopping/.test(t)) b.add("shopping");
  return [...b];
}

/** Wikipedia geosearch 결과를 POI 후보로. 유명(notable) 처리, 비관광 문서 제외. */
export function wikiFallbackSeeds(wiki: WikiArticle[]): PoiSeed[] {
  return wiki
    .filter((w) => !WIKI_BLOCK.test(w.title))
    .map((w) => {
      const cats = inferCategoriesFromTitle(w.title);
      return {
        name: w.title,
        name_en: w.title,
        location: w.location,
        categories: cats,
        notable: true, // 위키백과 등재 = 유명
        origin: "wiki" as const,
      };
    });
}

/**
 * OSM 후보(정보 풍부) 우선, OSM 에 없는 위키 명소를 추가 병합.
 * 위키 명소가 OSM 지점과 근접하면 on_osm=true(현존·구글검색 가능성) 표시.
 */
export function mergeByProximity(osmSeeds: PoiSeed[], wikiSeeds: PoiSeed[]): PoiSeed[] {
  const out: PoiSeed[] = osmSeeds.map((s) => ({ ...s, origin: "osm", on_osm: true }) as PoiSeed);
  for (const w of wikiSeeds) {
    const near = osmSeeds.some((o) => haversineMeters(o.location, w.location) <= TOLERANCE.geo_distance_m);
    if (near) continue; // OSM 에 이미 있으면 중복 → OSM 것 사용
    out.push({ ...w, on_osm: false });
  }
  return out;
}

/** 폐관/철거/이전 등 '현재 방문 불가/구글 미검색' 가능성이 높은 설명. */
const DEFUNCT_RE =
  /\b(former|formerly|closed|defunct|demolished|no longer|abolished|disused|abandoned|relocated|ceased|was a|were a|used to be|permanently closed|closed in \d{4})\b|폐관|폐업|철거|이전함/i;

/** 유명도 신호(위키 설명에 자주 등장). */
const FAME_RE = /famous|popular|iconic|landmark|one of the|most (visited|famous)|major|well-known|renowned|must-see|symbol of|largest|oldest|tallest/i;

/**
 * 유명도 점수 — 무명 신사보다 오사카성 같은 유명 명소를 상위로.
 * OSM 관광 태그(실제 명소) + 위키 설명 분량(=문서 크기=인지도) + 유명 키워드.
 */
export function fameScore(seed: PoiSeed): number {
  let s = 0;
  if (seed.on_osm) s += 4; // OSM 관광 태그 = 실제 방문 명소
  if (seed.notable) s += 2;
  const desc = seed.description ?? "";
  s += Math.min(desc.length / 40, 4); // 설명 길수록 유명
  if (FAME_RE.test(desc)) s += 3;
  s += Math.min((seed.categories ?? []).length, 2);
  return s;
}

export function isDefunctDescription(desc?: string): boolean {
  return !!desc && DEFUNCT_RE.test(desc);
}

/** 관공서·기업 등 '관광 대상 아님'을 설명으로 감지. */
const NON_ATTRACTION_DESC =
  /government|agency|ministry|administration|company|corporation|headquarters|organization|organisation|authority|institution|정부|기관|공사|공단|본사|기업|회사|대학|학교|병원|법원|관공서/i;
/** 실제 방문 대상(관광지) 신호. */
const ATTRACTION_DESC =
  /temple|shrine|museum|park|garden|castle|palace|tower|market|gallery|monument|memorial|zoo|aquarium|landmark|historic|cathedral|church|mosque|observ|waterfall|mountain|\blake\b|beach|island|bridge|\bgate\b|square|plaza|hot spring|onsen|theme park|shopping|statue|\btomb\b|ruins|\bfort\b|pagoda|pavilion|사찰|사원|신사|박물관|공원|정원|성\b|시장|미술관|기념|전망|타워|해변|폭포|유적|사당/i;

/**
 * 관광 대상인지 판정 — '기본 허용'. 명백한 관공서·기업 신호(설명)일 때만 제외.
 * (WIKI_BLOCK 이 제목 단계에서 이미 역/학교/관청을 걸렀고, 사찰의 일본식 이름
 *  -ji/-taisha 처럼 관광 키워드가 이름에 없어도 유명 명소는 살려야 하므로
 *  긍정 신호를 '요구'하지 않는다.)
 */
export function isVisitorAttraction(seed: PoiSeed): boolean {
  const text = `${seed.name} ${seed.name_en ?? ""} ${seed.description ?? ""}`;
  if (NON_ATTRACTION_DESC.test(text) && !ATTRACTION_DESC.test(text)) return false;
  return true;
}

/** 종일 체류형(테마파크 등) 판별. */
export function inferAllDay(name: string, categories: string[] | undefined): boolean {
  const t = name.toLowerCase();
  if (/universal|disney|studios|legoland|랜드|월드|테마파크|theme\s?park/.test(t)) return true;
  return (categories ?? []).includes("activity") && /park|land|world/.test(t);
}
