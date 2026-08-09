import "server-only";
import type { GeoPoint } from "@/core/types/domains";
import type { PoiSeed, RestaurantSeed, WikiArticle } from "../poi-build";
import { classifyTags, notableFromTags } from "../poi-select";
import { fetchJson } from "@/lib/http";

interface OverpassEl {
  lat?: number;
  lon?: number;
  center?: { lat: number; lon: number };
  tags?: Record<string, string>;
}
interface OverpassResp {
  elements: OverpassEl[];
}

const PRICE_MAP: Record<string, 1 | 2 | 3 | 4> = {
  cheap: 1,
  moderate: 2,
  expensive: 3,
  fine_dining: 4,
};

/** 커피 체인 등 식사로 부적절한 이름(스타벅스 등) 배제. */
const COFFEE_RE = /star\s*bucks|스타벅스|tully|coffee|카페|커피|doutor|excelsior|커피빈|coffee\s*bean/i;
/** 미개업/폐업/임시휴업 등 방문 불가 식당 배제. */
const NOT_OPEN_RE = /即將開幕|即将开业|opening soon|coming soon|準備中|준비\s*중|临时关闭|臨時休業|temporarily closed|permanently closed|폐업|closed down/i;
/**
 * '맛집'이 아닌 패스트푸드/저가 캐주얼 체인 — 여행 저녁 후보에서 제외.
 * (스타벅스·후터스·피자헛 등. 이치란 등 관광객 인기 라멘 체인은 제외하지 않음)
 */
const CHAIN_RE =
  /pizza\s*hut|必胜客|hooters|\bkfc\b|케이에프씨|肯德基|맥도날드|mcdonald|麦当劳|マクドナルド|버거킹|burger\s*king|汉堡王|subway|서브웨이|saizeriya|サイゼリヤ|萨莉亚|롯데리아|lotteria|모스버거|mos\s*burger|吉野家|yoshinoya|すき家|sukiya|松屋|matsuya|domino|도미노|papa\s*john|taco\s*bell|타코벨|wendy|denny'?s|デニーズ|ガスト|\bgusto\b|王将|ohsho|ちゃお|\bbabbi\b|텐카이핀|텐카|천가|くら寿司|kura\s*sushi|스시로|sushiro|はま寿司|hama\s*sushi/i;

function names(tags: Record<string, string>): Pick<PoiSeed, "name" | "name_en" | "name_ko"> {
  const local = tags["name"];
  const en = tags["name:en"];
  const ko = tags["name:ko"];
  const name = local ?? en ?? ko ?? "";
  return {
    name,
    ...(en && en !== name ? { name_en: en } : {}),
    ...(ko && ko !== name ? { name_ko: ko } : {}),
  };
}

/**
 * 관광지 발굴 — 명소/박물관/성/사찰/공원/전망대 등 폭넓게. 한 번의 Overpass 쿼리로
 * 이름(현지/영/한)·좌표·카테고리·유명도(위키데이터)를 받는다.
 */
export async function discoverPois(center: GeoPoint, radius = 12000, limit = 60): Promise<PoiSeed[]> {
  const filters = [
    `nwr["tourism"~"attraction|museum|viewpoint|gallery|zoo|theme_park|aquarium"]["name"]`,
    `nwr["historic"~"castle|monument|memorial|ruins|archaeological_site|temple|shrine"]["name"]`,
    `nwr["leisure"~"park|garden"]["name"]["wikidata"]`,
    `nwr["amenity"="place_of_worship"]["name"]["wikidata"]`,
  ];
  const els = await overpassUnion(filters, center, radius, limit);
  return els.flatMap((el) => {
    const loc = coord(el);
    const tags = el.tags ?? {};
    const nm = names(tags);
    if (!loc || !nm.name) return [];
    const oh = tags["opening_hours"];
    const fee = tags["fee"];
    const seed: PoiSeed = {
      ...nm,
      location: loc,
      categories: classifyTags(tags),
      notable: notableFromTags(tags),
      ...(oh ? { opening_hours: [oh] } : {}),
      ...(fee === "no" ? { admission_fee_local: 0 } : {}),
    };
    return [seed];
  });
}

/**
 * 맛집 발굴 — 제대로 된 '식당'만(카페/패스트푸드/저가 체인 배제).
 * 품질 신호(미쉐린·위키데이터 등재·요리종류·영업시간)로 점수화해 상위 맛집을
 * 먼저 돌려준다. 리뷰 API 는 무료가 없으므로 점수를 지어내지 않고(§0) OSM 이
 * 보유한 실제 태그만 근거로 삼는다.
 */
export async function discoverRestaurants(center: GeoPoint, radius = 7000, limit = 60): Promise<RestaurantSeed[]> {
  const els = await overpassUnion([`nwr["amenity"="restaurant"]["name"]`], center, radius, limit);
  const seeds = els.flatMap((el) => {
    const loc = coord(el);
    const tags = el.tags ?? {};
    const nm = names(tags);
    if (!loc || !nm.name) return [];
    const cuisine = tags["cuisine"];
    // 커피/카페성 식당은 저녁 후보에서 제외
    if (cuisine && /coffee_shop|cafe/.test(cuisine)) return [];
    const nameText = `${nm.name} ${nm.name_en ?? ""}`;
    if (COFFEE_RE.test(nameText) || CHAIN_RE.test(nameText)) return []; // 커피·저가 체인 제외
    // 미개업/폐업/임시휴업 식당 제외
    if (NOT_OPEN_RE.test(nameText) || tags["opening_hours"] === "closed" || tags["disused"] === "yes") return [];
    const oh = tags["opening_hours"];
    const price = tags["price"] ? PRICE_MAP[tags["price"]] : undefined;
    // 품질 신호(실제 OSM 태그)
    const michelin = Boolean(
      tags["michelin"] || tags["michelin_stars"] || tags["stars"] || /michelin/i.test(JSON.stringify(tags)),
    );
    const notable = Boolean(tags["wikidata"] || tags["wikipedia"]) && !tags["brand"] && !tags["brand:wikidata"];
    const branded = Boolean(tags["brand"] || tags["brand:wikidata"]); // 체인 브랜드(감점)
    const seed: RestaurantSeed = {
      ...nm,
      location: loc,
      ...(oh ? { opening_hours: [oh] } : {}),
      ...(price ? { price_level: price } : {}),
      ...(cuisine ? { cuisine } : {}),
      ...(michelin ? { michelin: true } : {}),
      ...(notable ? { notable: true } : {}),
      ...(branded ? { branded: true } : {}),
    };
    return [seed];
  });
  // 품질 점수 내림차순 — 미쉐린/위키등재/요리정보가 있는 맛집을 앞으로
  return seeds.sort((a, b) => restaurantScore(b) - restaurantScore(a));
}

/** 식당 품질 점수 — OSM 실태그만 근거(리뷰 점수는 지어내지 않음). */
function restaurantScore(s: RestaurantSeed): number {
  let score = 0;
  if (s.michelin) score += 6; // 미쉐린 표기
  if (s.notable) score += 5; // 위키데이터/위키백과 등재 = 유명 맛집
  if (s.cuisine) score += 2; // 요리종류 정보(정성적 충실도)
  if (s.opening_hours) score += 1;
  if (s.price_level && s.price_level >= 3) score += 1; // 파인다이닝 소폭 우대
  if (s.branded) score -= 3; // 체인 브랜드 감점
  return score;
}

/** 도시 인근 Wikipedia 문서(좌표) — POI 교차검증·유명도 판정 후보. */
export async function wikiNearby(center: GeoPoint, radius = 12000, limit = 400): Promise<WikiArticle[]> {
  const url =
    `https://en.wikipedia.org/w/api.php?action=query&list=geosearch&format=json` +
    `&gscoord=${center.lat}%7C${center.lng}&gsradius=${radius}&gslimit=${limit}`;
  const data = await fetchJson<{ query?: { geosearch?: { title: string; lat: number; lon: number }[] } }>(url, {
    timeoutMs: 8_000,
  });
  return (data.query?.geosearch ?? []).map((g) => ({
    title: g.title,
    location: { lat: g.lat, lng: g.lon },
  }));
}

/**
 * 여러 필터의 합집합(union) 쿼리를 올바르게 구성한다.
 * 각 필터에 (around) 와 세미콜론을 붙여야 유효한 Overpass QL 이 된다.
 */
/** Overpass 공개 미러 — 하나가 막히면 다음으로 폴백(짧은 타임아웃). */
const OVERPASS_MIRRORS = [
  "https://overpass-api.de/api/interpreter",
  "https://overpass.kumi.systems/api/interpreter",
];

async function overpassUnion(
  filters: string[],
  center: GeoPoint,
  radius: number,
  limit: number,
): Promise<OverpassEl[]> {
  const body = filters
    .map((f) => `${f}(around:${radius},${center.lat},${center.lng});`)
    .join("");
  const q = `[out:json][timeout:12];(${body});out center ${limit};`;
  const enc = encodeURIComponent(q);
  for (const mirror of OVERPASS_MIRRORS) {
    try {
      // 짧은 타임아웃(7s) — Overpass 는 보강용이므로 느리면 즉시 폴백/포기
      const data = await fetchJson<OverpassResp>(`${mirror}?data=${enc}`, { timeoutMs: 6_000 });
      if (data.elements) return data.elements;
    } catch {
      // 다음 미러로 폴백
    }
  }
  return [];
}

function coord(el: OverpassEl): GeoPoint | null {
  const lat = el.lat ?? el.center?.lat;
  const lon = el.lon ?? el.center?.lon;
  return lat === undefined || lon === undefined ? null : { lat, lng: lon };
}
