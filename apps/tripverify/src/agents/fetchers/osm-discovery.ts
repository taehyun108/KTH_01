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

/** 맛집 발굴 — 제대로 된 '식당'만(카페/패스트푸드/커피 배제). */
export async function discoverRestaurants(center: GeoPoint, radius = 7000, limit = 40): Promise<RestaurantSeed[]> {
  const els = await overpassUnion([`nwr["amenity"="restaurant"]["name"]`], center, radius, limit);
  return els.flatMap((el) => {
    const loc = coord(el);
    const tags = el.tags ?? {};
    const nm = names(tags);
    if (!loc || !nm.name) return [];
    const cuisine = tags["cuisine"];
    // 커피/카페성 식당은 저녁 후보에서 제외
    if (cuisine && /coffee_shop|cafe/.test(cuisine)) return [];
    const nameText = `${nm.name} ${nm.name_en ?? ""}`;
    if (COFFEE_RE.test(nameText)) return [];
    // 미개업/폐업/임시휴업 식당 제외
    if (NOT_OPEN_RE.test(nameText) || tags["opening_hours"] === "closed" || tags["disused"] === "yes") return [];
    const oh = tags["opening_hours"];
    const price = tags["price"] ? PRICE_MAP[tags["price"]] : undefined;
    const seed: RestaurantSeed = {
      ...nm,
      location: loc,
      ...(oh ? { opening_hours: [oh] } : {}),
      ...(price ? { price_level: price } : {}),
      ...(cuisine ? { cuisine } : {}),
    };
    return [seed];
  });
}

/** 도시 인근 Wikipedia 문서(좌표) — POI 교차검증·유명도 판정 후보. */
export async function wikiNearby(center: GeoPoint, radius = 12000, limit = 500): Promise<WikiArticle[]> {
  const url =
    `https://en.wikipedia.org/w/api.php?action=query&list=geosearch&format=json` +
    `&gscoord=${center.lat}%7C${center.lng}&gsradius=${radius}&gslimit=${limit}`;
  const data = await fetchJson<{ query?: { geosearch?: { title: string; lat: number; lon: number }[] } }>(url);
  return (data.query?.geosearch ?? []).map((g) => ({
    title: g.title,
    location: { lat: g.lat, lng: g.lon },
  }));
}

/**
 * 여러 필터의 합집합(union) 쿼리를 올바르게 구성한다.
 * 각 필터에 (around) 와 세미콜론을 붙여야 유효한 Overpass QL 이 된다.
 */
/** Overpass 공개 미러 — 하나가 막히면 다음으로 폴백(클라우드 안정성). */
const OVERPASS_MIRRORS = [
  "https://overpass-api.de/api/interpreter",
  "https://overpass.kumi.systems/api/interpreter",
  "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
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
  const q = `[out:json][timeout:25];(${body});out center ${limit};`;
  const enc = encodeURIComponent(q);
  for (const mirror of OVERPASS_MIRRORS) {
    try {
      const data = await fetchJson<OverpassResp>(`${mirror}?data=${enc}`, { timeoutMs: 16_000 });
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
