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
  const nm = `${seed.name} ${seed.name_en ?? ""}`;
  // 세계적 마퀴 명소(유니버설 등)·아이코닉 랜드마크는 컨셉과 무관하게 상위 후보 보장
  if (MARQUEE_RE.test(nm)) score += 8;
  if (ICONIC_RE.test(nm)) score += 8;
  if (isThemeParkCats(seed.categories)) score += 3;
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
  // 테마파크(유니버설·디즈니·레고랜드 등) — 세계적 명소, 종일 코스
  if (/universal\s*studios|disney|legoland|ghibli|theme\s*park|遊園地|테마파크|랜드\b|월드\b|everland|lotte\s*world/.test(t)) {
    b.add("activity");
    b.add("family");
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
  /\b(former|formerly|closed|defunct|demolished|no longer|abolished|disused|abandoned|relocated|ceased|was an?|were an?|used to be|permanently closed|closed in \d{4})\b|폐관|폐업|철거|이전함/i;

/**
 * 아파트·주거·오피스 등 '관광지가 아닌 건물' — 무조건 제외(ATTRACTION 키워드보다 우선).
 * (예: "The Tower Osaka is a high rise apartment building" → 관광지 아님)
 */
const RESIDENTIAL_RE =
  /\b(apartment|residential|condominium|condo|housing|dormitory|office building|mixed-use|high[-\s]?rise (apartment|residential|building|condominium))\b|아파트|주상복합|오피스텔|주거/i;

/** 유명도 신호(위키 설명에 자주 등장). */
const FAME_RE = /famous|popular|iconic|landmark|one of the|most (visited|famous)|major|well-known|renowned|must-see|symbol of|largest|oldest|tallest/i;

/**
 * 세계적 마퀴 명소 — 여행 순위 상위에 반드시 오르는 대표 명소/테마파크.
 * (유니버설 스튜디오·디즈니·레고랜드 등 종일 테마파크와 국가급 랜드마크)
 * 설명이 아직 없어도 이름만으로 최상위 가중치를 준다 → 유명순 일정 보장.
 */
const MARQUEE_RE =
  /universal\s*studios|디즈니|disney(land| sea| resort| world)?|legoland|레고랜드|everland|에버랜드|lotte\s*world|롯데월드|ghibli|지브리|teamlab|팀랩/i;

/**
 * 세계적 아이코닉 랜드마크 — 그 도시를 대표하는 '1순위 필수 명소'.
 * 이름만으로 최상위 가중치를 줘, 검색 시 대표 명소가 먼저 나오도록 한다
 * (예: 바르셀로나 → 사그라다 파밀리아). 도시별 상징물 위주로 유지·확장.
 */
const ICONIC_RE = new RegExp(
  [
    // 스페인/바르셀로나
    "sagrada\\s*fam", "사그라다", "park\\s*güell", "park\\s*guell", "구엘", "casa\\s*batll", "casa\\s*mil", "카사\\s*바트요", "la\\s*rambla", "montjuïc|montjuic",
    // 프랑스/파리
    "eiffel", "에펠", "louvre", "루브르", "notre[-\\s]?dame", "노트르담", "arc\\s*de\\s*triomphe", "개선문", "versailles", "베르사유", "sacr[eé][-\\s]?c[oœ]ur",
    // 이탈리아/로마·기타
    "colosseum|colosseo", "콜로세움", "trevi", "트레비", "pantheon", "판테온", "vatican|st\\.?\\s*peter", "바티칸", "duomo", "두오모", "leaning\\s*tower|피사",
    // 영국/런던
    "big\\s*ben", "빅벤", "tower\\s*bridge", "타워브리지", "london\\s*eye", "런던아이", "buckingham", "버킹엄", "tower\\s*of\\s*london",
    // 미국/뉴욕 등
    "statue\\s*of\\s*liberty", "자유의\\s*여신", "times\\s*square", "타임스퀘어", "empire\\s*state", "엠파이어", "golden\\s*gate", "금문교",
    // 독일/네덜란드/기타 유럽
    "brandenburg", "브란덴부르크", "neuschwanstein", "노이슈반슈타인", "anne\\s*frank", "rijksmuseum",
    // 아시아 대표
    "petronas", "페트로나스", "marina\\s*bay\\s*sands", "마리나\\s*베이", "merlion", "멀라이언", "grand\\s*palace", "왕궁", "wat\\s*arun|wat\\s*pho",
    "angkor", "앙코르", "taj\\s*mahal", "타지마할", "great\\s*wall", "만리장성", "forbidden\\s*city", "자금성", "the\\s*bund", "와이탄",
    "tokyo\\s*tower", "도쿄타워", "tokyo\\s*sky\\s*tree|skytree", "스카이트리", "senso[-\\s]?ji|sensō[-\\s]?ji", "센소지", "fushimi\\s*inari", "후시미",
    "kinkaku", "금각사", "gyeongbok", "경복궁", "n\\s*seoul\\s*tower|namsan", "남산",
  ].join("|"),
  "i",
);

/** 종일 테마파크 유형(카테고리로 판단) — 대표 명소로 강하게 우대. */
function isThemeParkCats(cats: string[] | undefined): boolean {
  const c = cats ?? [];
  return c.includes("activity") && c.includes("family");
}

/**
 * 유명도 점수 — 무명 신사보다 오사카성·유니버설 같은 유명 명소를 상위로.
 * 마퀴 명소(테마파크·랜드마크) > OSM 관광태그 + 위키 설명 분량(인지도) + 유명 키워드.
 */
export function fameScore(seed: PoiSeed): number {
  let s = 0;
  const name = `${seed.name} ${seed.name_en ?? ""}`;
  if (MARQUEE_RE.test(name)) s += 10; // 세계적 명소(테마파크 등) 최상위
  if (ICONIC_RE.test(name)) s += 11; // 도시 대표 아이코닉 랜드마크(사그라다 등) 1순위
  if (isThemeParkCats(seed.categories)) s += 4; // 테마파크 유형(종일 코스)
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
  // 아파트/주거/오피스는 이름에 'tower' 등 관광 키워드가 있어도 무조건 제외
  if (RESIDENTIAL_RE.test(seed.description ?? "")) return false;
  if (NON_ATTRACTION_DESC.test(text) && !ATTRACTION_DESC.test(text)) return false;
  return true;
}

/** 종일 체류형(테마파크 등) 판별. */
export function inferAllDay(name: string, categories: string[] | undefined): boolean {
  const t = name.toLowerCase();
  if (/universal|disney|studios|legoland|랜드|월드|테마파크|theme\s?park/.test(t)) return true;
  return (categories ?? []).includes("activity") && /park|land|world/.test(t);
}
