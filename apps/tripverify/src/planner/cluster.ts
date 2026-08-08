import type { GeoPoint } from "@/core/types/domains";
import { haversineMeters } from "@/lib/geo";

export interface Place {
  id: string;
  location: GeoPoint;
  /** 방문 권장 시간대(감수성). 동선 정렬 후 시간대 순으로 재배치. */
  time_pref?: "morning" | "day" | "evening";
}

/**
 * 일자별 지리 클러스터링 (§6). K-means (결정론적 farthest-point 시딩).
 * 같은 날 방문 POI 를 지리적으로 뭉쳐 이동거리를 줄인다.
 *
 * @param places 대상 장소
 * @param k      군집 수(=여행 일수)
 * @returns      각 군집의 place id 배열 (길이 k)
 */
export function clusterByDay(places: Place[], k: number): string[][] {
  if (k <= 1 || places.length <= k) {
    // 장소가 적으면 한 곳에 한 군집씩
    return distributeTrivially(places, k);
  }

  // 용량 균형 배정: 각 날이 비슷한 수의 장소를 갖도록(하루 편중 방지).
  // farthest 시딩으로 대략적 지역 중심을 잡고, 용량 한도 내에서 최근접 배정.
  const centers = seedFarthest(places, k);
  const capacity = Math.ceil(places.length / k);
  const counts = new Array(k).fill(0);
  const assignment = new Array<number>(places.length).fill(-1);

  // '가장 확신 있는(최근접이 가까운)' 장소부터 배정
  const order = places
    .map((p, i) => ({ i, d: minCenterDist(p.location, centers) }))
    .sort((a, b) => a.d - b.d);

  for (const { i } of order) {
    const ranked = centers
      .map((c, ci) => ({ ci, d: haversineMeters(places[i]!.location, c) }))
      .sort((a, b) => a.d - b.d);
    // 용량이 남은 가장 가까운 군집에 배정
    let target = ranked.find((r) => counts[r.ci] < capacity)?.ci ?? ranked[0]!.ci;
    assignment[i] = target;
    counts[target]++;
  }

  const clusters: string[][] = Array.from({ length: k }, () => []);
  places.forEach((p, i) => clusters[assignment[i]!]!.push(p.id));
  return clusters;
}

function minCenterDist(p: GeoPoint, centers: GeoPoint[]): number {
  return Math.min(...centers.map((c) => haversineMeters(p, c)));
}

function distributeTrivially(places: Place[], k: number): string[][] {
  const clusters: string[][] = Array.from({ length: Math.max(k, 1) }, () => []);
  places.forEach((p, i) => clusters[i % clusters.length]!.push(p.id));
  return clusters;
}

/** farthest-point 시딩: 첫 중심을 전체 centroid 최근접점으로, 이후 최원점 선택. */
function seedFarthest(places: Place[], k: number): GeoPoint[] {
  const centers: GeoPoint[] = [places[0]!.location];
  while (centers.length < k) {
    let far: GeoPoint = places[0]!.location;
    let farDist = -1;
    for (const p of places) {
      const d = Math.min(...centers.map((c) => haversineMeters(p.location, c)));
      if (d > farDist) {
        farDist = d;
        far = p.location;
      }
    }
    centers.push(far);
  }
  return centers;
}

