import "server-only";
import type { GeoPoint, Poi, Restaurant } from "@/core/types/domains";
import type { Observation } from "@/core/verification/observation";
import type { SourceReader } from "../types";
import { fetchJson, nowISO } from "@/lib/http";

export interface PlaceArgs {
  name: string;
  center: GeoPoint;
  radius_m?: number;
}

/** OSM opening_hours 태그 → 요일 배열은 파싱이 복잡하므로 원문 보관만 한다. */
function osmOpeningToArray(oh?: string): (string | null)[] | undefined {
  return oh ? [oh] : undefined; // 정규화는 planner 이전 단계에서 별도 처리
}

// ── Overpass (OSM) — tier 2 ───────────────────────────────────────────────
interface OverpassResp {
  elements: {
    lat?: number;
    lon?: number;
    center?: { lat: number; lon: number };
    tags?: Record<string, string>;
  }[];
}

export const overpassPoiReader: SourceReader<PlaceArgs, Poi> = async (args) => {
  const el = await overpassByName(args, "tourism");
  if (!el) return [];
  const oh = osmOpeningToArray(el.tags?.["opening_hours"]);
  const fee = el.tags?.["fee"] === "no" ? 0 : null;
  return [
    {
      value: {
        name: args.name,
        location: el.loc,
        ...(oh ? { opening_hours: oh } : {}),
        admission_fee_local: fee,
      },
      source: {
        name: "OpenStreetMap/Overpass",
        url: "https://overpass-api.de/",
        tier: 2,
        retrieved_at: nowISO(),
      },
      pass: 1,
    },
  ];
};

export const overpassFoodReader: SourceReader<PlaceArgs, Restaurant> = async (args) => {
  const el = await overpassByName(args, "amenity");
  if (!el) return [];
  const oh = osmOpeningToArray(el.tags?.["opening_hours"]);
  return [
    {
      value: {
        name: args.name,
        location: el.loc,
        ...(oh ? { opening_hours: oh } : {}),
      },
      source: {
        name: "OpenStreetMap/Overpass",
        url: "https://overpass-api.de/",
        tier: 2,
        retrieved_at: nowISO(),
      },
      pass: 1,
    },
  ];
};

async function overpassByName(
  args: PlaceArgs,
  key: string,
): Promise<{ loc: GeoPoint; tags?: Record<string, string> } | null> {
  const r = args.radius_m ?? 20_000;
  const q =
    `[out:json][timeout:20];` +
    `nwr["${key}"]["name"="${args.name.replace(/"/g, "")}"](around:${r},${args.center.lat},${args.center.lng});` +
    `out center 1;`;
  const data = await fetchJson<OverpassResp>(
    `https://overpass-api.de/api/interpreter?data=${encodeURIComponent(q)}`,
  );
  const el = data.elements[0];
  if (!el) return null;
  const lat = el.lat ?? el.center?.lat;
  const lon = el.lon ?? el.center?.lon;
  if (lat === undefined || lon === undefined) return null;
  return { loc: { lat, lng: lon }, ...(el.tags ? { tags: el.tags } : {}) };
}

// ── Wikipedia GeoSearch — tier 2, OSM 과 독립 도메인 ────────────────────────
interface WikiGeoResp {
  query?: { geosearch?: { title: string; lat: number; lon: number }[] };
}

export const wikipediaPoiReader: SourceReader<PlaceArgs, Poi> = async (args) => {
  const url =
    `https://en.wikipedia.org/w/api.php?action=query&list=geosearch&format=json` +
    `&gscoord=${args.center.lat}%7C${args.center.lng}&gsradius=${args.radius_m ?? 20000}&gslimit=50`;
  const data = await fetchJson<WikiGeoResp>(url);
  const hit = data.query?.geosearch?.find((g) =>
    g.title.toLowerCase().includes(args.name.toLowerCase()),
  );
  if (!hit) return [];
  return [
    {
      value: { name: args.name, location: { lat: hit.lat, lng: hit.lon } },
      source: {
        name: "Wikipedia GeoSearch",
        url: "https://en.wikipedia.org/",
        tier: 2,
        retrieved_at: nowISO(),
      },
      pass: 2,
    },
  ];
};

export const livePoiReaders: SourceReader<PlaceArgs, Poi>[] = [
  overpassPoiReader,
  wikipediaPoiReader,
];
export const liveFoodReaders: SourceReader<PlaceArgs, Restaurant>[] = [overpassFoodReader];

/** Overpass 로 후보 명소/식당 이름을 발굴한다(교차검증 전 단계). */
export async function discoverNames(
  center: GeoPoint,
  kind: "poi" | "food",
  radius_m = 8000,
  limit = 20,
): Promise<string[]> {
  const filter =
    kind === "poi"
      ? `nwr["tourism"~"attraction|museum|viewpoint|artwork|zoo|theme_park"]["name"]`
      : `nwr["amenity"~"restaurant|cafe"]["name"]["cuisine"]`;
  const q =
    `[out:json][timeout:25];${filter}(around:${radius_m},${center.lat},${center.lng});out center ${limit};`;
  const data = await fetchJson<OverpassResp>(
    `https://overpass-api.de/api/interpreter?data=${encodeURIComponent(q)}`,
  );
  const names = data.elements
    .map((e) => e.tags?.["name:en"] ?? e.tags?.["name"])
    .filter((n): n is string => typeof n === "string");
  return [...new Set(names)].slice(0, limit);
}
