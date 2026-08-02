import type { GeoPoint } from "@/core/types/domains";
import type { TransportMode } from "./types";
import type { MatrixProvider, MatrixResult } from "./fetchers/routing";
import { clusterByDay, type Place } from "@/planner/cluster";
import { optimizeOrder, pathCost, type Matrix } from "@/planner/tsp";

export interface RoutePlanInput {
  places: Place[];
  days: number;
  mode: TransportMode;
}

export interface DayRoute {
  day_index: number;
  ordered_place_ids: string[];
  /** 순서대로 이동한 총 소요시간(초). */
  total_travel_seconds: number;
}

export interface RoutePlan {
  days: DayRoute[];
  estimated: boolean; // 매트릭스가 추정치인지
  source_name: string;
}

/**
 * route-agent (§2, §6). 이동시간 매트릭스를 조회(수집)하고 일자별로 클러스터링 후
 * 각 날의 방문 순서를 TSP(2-opt)로 최적화한다. 직선거리가 아닌 실 소요시간을 쓴다.
 * 판단(재배치 경고 등)은 planner 소관 — 여기서는 순서·소요시간 산출까지.
 */
export async function routeAgent(
  input: RoutePlanInput,
  provider: MatrixProvider,
): Promise<RoutePlan> {
  const clusters = clusterByDay(input.places, input.days);
  const days: DayRoute[] = [];
  let estimated = false;
  let source_name = "";

  for (let d = 0; d < clusters.length; d++) {
    const ids = clusters[d]!;
    const pts: GeoPoint[] = ids.map((id) => byId(input.places, id).location);
    if (pts.length <= 1) {
      days.push({ day_index: d, ordered_place_ids: ids, total_travel_seconds: 0 });
      continue;
    }
    const mat: MatrixResult = await provider(pts, input.mode);
    estimated = estimated || mat.estimated;
    source_name = mat.source.name;
    const order = optimizeOrder(mat.durations as Matrix, 0);
    days.push({
      day_index: d,
      ordered_place_ids: order.map((i) => ids[i]!),
      total_travel_seconds: pathCost(mat.durations as Matrix, order),
    });
  }

  return { days, estimated, source_name };
}

function byId(places: Place[], id: string): Place {
  const p = places.find((x) => x.id === id);
  if (!p) throw new Error(`unknown place id: ${id}`);
  return p;
}
