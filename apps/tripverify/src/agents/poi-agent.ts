import type { GeoPoint, Poi, Restaurant } from "@/core/types/domains";
import type { VerifiedFact } from "@/core/types/verified-fact";
import type { Comparator } from "@/core/verification/observation";
import type { SourceReader } from "./types";
import type { PlaceArgs } from "./fetchers/places";
import { verify } from "@/core/verification/verifier";
import { TOLERANCE } from "@/core/verification/tolerance";
import { haversineMeters } from "@/lib/geo";

/**
 * 장소 비교자: '실존 + 위치 일치'가 핵심 검증 대상이다(§10 실존 0건).
 * 좌표가 100m 이내로 여러 독립 출처에서 확인돼야 medium 이상이 된다.
 * (opening_hours/입장료는 채택 출처의 값을 승계 — 세부 필드 교차검증은 추후 확장)
 */
function locationComparator<T extends { location: GeoPoint }>(): Comparator<T> {
  return {
    agree: (a, b) => haversineMeters(a.location, b.location) <= TOLERANCE.geo_distance_m,
    deviation: (a, b) => haversineMeters(a.location, b.location),
  };
}

/**
 * poi-agent (§2). 후보 장소명 각각에 대해 독립 출처의 좌표를 교차검증한다.
 * 검증 실패(단일 출처 등) 장소는 low → planner 가 일정에서 제외 → 유령 장소 0건.
 */
export async function poiAgent(
  names: string[],
  args: { center: GeoPoint; radius_m?: number },
  readers: SourceReader<PlaceArgs, Poi>[],
): Promise<VerifiedFact<Poi>[]> {
  return verifyNamedPlaces<Poi>(names, args, readers);
}

/** food-agent (§2). POI 와 동일 로직, Restaurant 타입. */
export async function foodAgent(
  names: string[],
  args: { center: GeoPoint; radius_m?: number },
  readers: SourceReader<PlaceArgs, Restaurant>[],
): Promise<VerifiedFact<Restaurant>[]> {
  return verifyNamedPlaces<Restaurant>(names, args, readers);
}

async function verifyNamedPlaces<T extends { name: string; location: GeoPoint }>(
  names: string[],
  args: { center: GeoPoint; radius_m?: number },
  readers: SourceReader<PlaceArgs, T>[],
): Promise<VerifiedFact<T>[]> {
  const comparator = locationComparator<T>();
  const out = await Promise.all(
    names.map(async (name) => {
      const placeArgs: PlaceArgs = {
        name,
        center: args.center,
        ...(args.radius_m !== undefined ? { radius_m: args.radius_m } : {}),
      };
      const settled = await Promise.allSettled(readers.map((r) => r(placeArgs)));
      const obs = settled.flatMap((s) => (s.status === "fulfilled" ? s.value : []));
      return verify<T>(obs, {
        comparator,
        tolerance: TOLERANCE.geo_distance_m,
      });
    }),
  );
  return out;
}
