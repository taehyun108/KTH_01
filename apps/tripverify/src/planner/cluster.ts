import type { GeoPoint } from "@/core/types/domains";
import { haversineMeters, centroid } from "@/lib/geo";

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

  let centers = seedFarthest(places, k);
  let assignment: number[] = new Array(places.length).fill(0);

  for (let iter = 0; iter < 50; iter++) {
    let changed = false;
    // assign
    for (let i = 0; i < places.length; i++) {
      const best = nearestCenter(places[i]!.location, centers);
      if (assignment[i] !== best) {
        assignment[i] = best;
        changed = true;
      }
    }
    // update
    const next: GeoPoint[] = [];
    for (let c = 0; c < k; c++) {
      const members = places.filter((_, i) => assignment[i] === c).map((p) => p.location);
      next.push(members.length > 0 ? centroid(members) : centers[c]!);
    }
    centers = next;
    if (!changed) break;
  }

  const clusters: string[][] = Array.from({ length: k }, () => []);
  places.forEach((p, i) => clusters[assignment[i]!]!.push(p.id));
  return rebalanceEmpty(clusters, places);
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

function nearestCenter(p: GeoPoint, centers: GeoPoint[]): number {
  let best = 0;
  let bestD = Infinity;
  centers.forEach((c, i) => {
    const d = haversineMeters(p, c);
    if (d < bestD) {
      bestD = d;
      best = i;
    }
  });
  return best;
}

/** 빈 군집이 생기면 가장 큰 군집에서 한 개를 이동시켜 채운다. */
function rebalanceEmpty(clusters: string[][], places: Place[]): string[][] {
  const byId = new Map(places.map((p) => [p.id, p.location] as const));
  for (let c = 0; c < clusters.length; c++) {
    if (clusters[c]!.length > 0) continue;
    const biggest = clusters.reduce((a, b) => (b.length > a.length ? b : a), clusters[0]!);
    if (biggest.length <= 1) continue;
    const moved = biggest.pop()!;
    void byId;
    clusters[c]!.push(moved);
  }
  return clusters;
}
