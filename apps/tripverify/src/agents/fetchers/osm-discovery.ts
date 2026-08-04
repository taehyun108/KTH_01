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
  const els = await overpass(filters.join(""), center, radius, limit);
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
  const els = await overpass(`nwr["amenity"="restaurant"]["name"]`, center, radius, limit);
  return els.flatMap((el) => {
    const loc = coord(el);
    const tags = el.tags ?? {};
    const nm = names(tags);
    if (!loc || !nm.name) return [];
    const cuisine = tags["cuisine"];
    // 커피/카페성 식당은 저녁 후보에서 제외
    if (cuisine && /coffee_shop|cafe/.test(cuisine)) return [];
    if (COFFEE_RE.test(nm.name) || (nm.name_en && COFFEE_RE.test(nm.name_en))) return [];
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
export async function wikiNearby(center: GeoPoint, radius = 10000, limit = 200): Promise<WikiArticle[]> {
  const url =
    `https://en.wikipedia.org/w/api.php?action=query&list=geosearch&format=json` +
    `&gscoord=${center.lat}%7C${center.lng}&gsradius=${radius}&gslimit=${limit}`;
  const data = await fetchJson<{ query?: { geosearch?: { title: string; lat: number; lon: number }[] } }>(url);
  return (data.query?.geosearch ?? []).map((g) => ({
    title: g.title,
    location: { lat: g.lat, lng: g.lon },
  }));
}

async function overpass(filter: string, center: GeoPoint, radius: number, limit: number): Promise<OverpassEl[]> {
  const q = `[out:json][timeout:25];(${filter}(around:${radius},${center.lat},${center.lng}););out center ${limit};`;
  const data = await fetchJson<OverpassResp>(
    `https://overpass-api.de/api/interpreter?data=${encodeURIComponent(q)}`,
  );
  return data.elements ?? [];
}

function coord(el: OverpassEl): GeoPoint | null {
  const lat = el.lat ?? el.center?.lat;
  const lon = el.lon ?? el.center?.lon;
  return lat === undefined || lon === undefined ? null : { lat, lng: lon };
}
