import "server-only";
import type { GeoPoint } from "@/core/types/domains";
import type { TransportMode } from "../types";
import type { Source } from "@/core/types/verified-fact";
import type { Matrix } from "@/planner/tsp";
import { fetchJson, nowISO } from "@/lib/http";
import { haversineMeters } from "@/lib/geo";

export interface MatrixResult {
  durations: Matrix; // 초
  source: Source;
  estimated: boolean; // 실측(OSRM) vs 추정(하버사인)
}

export type MatrixProvider = (
  points: GeoPoint[],
  mode: TransportMode,
) => Promise<MatrixResult>;

const OSRM_PROFILE: Record<TransportMode, string> = {
  walk: "foot",
  car: "driving",
  transit: "driving", // OSRM 공개 서버는 대중교통 미지원 → driving 근사
};

/** OSRM table 서비스 (키 불필요, tier 2). 실측 소요시간. */
export const osrmMatrix: MatrixProvider = async (points, mode) => {
  const coords = points.map((p) => `${p.lng},${p.lat}`).join(";");
  const url = `https://router.project-osrm.org/table/v1/${OSRM_PROFILE[mode]}/${coords}?annotations=duration`;
  // 짧은 타임아웃(5s) — 라우팅은 보강이므로 느리면 즉시 추정으로 폴백(서버리스 시간예산 보호)
  const data = await fetchJson<{ durations: number[][] }>(url, { timeoutMs: 5_000 });
  return {
    durations: data.durations,
    source: {
      name: "OSRM",
      url: "https://router.project-osrm.org/",
      tier: 2,
      retrieved_at: nowISO(),
    },
    estimated: false,
  };
};

/** 하버사인 기반 추정 (오프라인 폴백, tier 3 '추정' 라벨). */
const SPEED_MPS: Record<TransportMode, number> = {
  walk: 1.4, // 5 km/h
  transit: 5.5, // ~20 km/h (정차 포함)
  car: 8.3, // ~30 km/h 도심
};
const DETOUR = 1.3; // 직선 대비 도로 우회 계수

export const haversineMatrix: MatrixProvider = async (points, mode) => {
  const n = points.length;
  const durations: Matrix = Array.from({ length: n }, () => new Array(n).fill(0));
  for (let i = 0; i < n; i++) {
    for (let j = 0; j < n; j++) {
      if (i === j) continue;
      const meters = haversineMeters(points[i]!, points[j]!) * DETOUR;
      durations[i]![j] = Math.round(meters / SPEED_MPS[mode]);
    }
  }
  return {
    durations,
    source: {
      name: "직선거리 추정(도로 우회 보정)",
      url: "https://tripverify.local/estimate",
      tier: 3,
      retrieved_at: nowISO(),
    },
    estimated: true,
  };
};

/**
 * OSRM 실패 시 추정으로 폴백하는 결합 프로바이더.
 * '스티키' — 한 번 실패하면 같은 요청 내 이후 호출은 곧장 추정을 쓴다(재시도로
 * 인한 시간낭비 방지 → 서버리스 60s 예산 보호).
 */
export function matrixWithFallback(primary: MatrixProvider = osrmMatrix): MatrixProvider {
  let primaryDead = false;
  return async (points, mode) => {
    if (primaryDead) return haversineMatrix(points, mode);
    try {
      return await primary(points, mode);
    } catch {
      primaryDead = true;
      return haversineMatrix(points, mode);
    }
  };
}
