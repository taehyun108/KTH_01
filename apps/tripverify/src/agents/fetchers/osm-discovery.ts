import "server-only";
import type { GeoPoint } from "@/core/types/domains";
import type { PoiSeed, RestaurantSeed, WikiArticle } from "../poi-build";
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

/** 관광지 발굴 — 한 번의 Overpass 쿼리로 이름+좌표+태그를 받는다(재조회 없음). */
export async function discoverPois(center: GeoPoint, radius = 9000, limit = 30): Promise<PoiSeed[]> {
  const els = await overpass(
    `nwr["tourism"~"attraction|museum|viewpoint|artwork|zoo|theme_park|gallery"]["name"]`,
    center,
    radius,
    limit,
  );
  return els.flatMap((el) => {
    const loc = coord(el);
    const name = el.tags?.["name:en"] ?? el.tags?.["name"];
    if (!loc || !name) return [];
    const oh = el.tags?.["opening_hours"];
    const fee = el.tags?.["fee"];
    const seed: PoiSeed = {
      name,
      location: loc,
      ...(oh ? { opening_hours: [oh] } : {}),
      ...(fee === "no" ? { admission_fee_local: 0 } : {}),
    };
    return [seed];
  });
}

/** 맛집 발굴 — cuisine 태그가 있는 식당/카페. */
export async function discoverRestaurants(center: GeoPoint, radius = 6000, limit = 24): Promise<RestaurantSeed[]> {
  const els = await overpass(
    `nwr["amenity"~"restaurant|cafe"]["name"]["cuisine"]`,
    center,
    radius,
    limit,
  );
  return els.flatMap((el) => {
    const loc = coord(el);
    const name = el.tags?.["name:en"] ?? el.tags?.["name"];
    if (!loc || !name) return [];
    const oh = el.tags?.["opening_hours"];
    const price = el.tags?.["price"] ? PRICE_MAP[el.tags["price"]] : undefined;
    const seed: RestaurantSeed = {
      name,
      location: loc,
      ...(oh ? { opening_hours: [oh] } : {}),
      ...(price ? { price_level: price } : {}),
    };
    return [seed];
  });
}

/** 도시 인근 Wikipedia 문서(좌표) — 한 번의 호출로 POI 교차검증 후보를 확보. */
export async function wikiNearby(center: GeoPoint, radius = 10000, limit = 100): Promise<WikiArticle[]> {
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
