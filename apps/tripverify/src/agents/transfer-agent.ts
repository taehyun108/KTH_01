import type { GeoPoint } from "@/core/types/domains";
import type { CityTransfer } from "@/core/types/itinerary";
import { verified } from "@/core/factory/make-fact";
import { haversineMeters } from "@/lib/geo";

export interface CityNode {
  name: string;
  center: GeoPoint;
}

/**
 * 도시 간 이동방법 계획 (§ 이동방법). 좌표 직선거리 기반 추정이므로
 * 신뢰도는 low(추정). 거리 구간에 따라 이동수단과 소요시간을 제안한다.
 * 실 교통 스케줄/요금은 별도 소스(항공/철도 API)로 보강해야 검증된다.
 */
export function planTransfers(cities: CityNode[], checkedAt = new Date().toISOString()): CityTransfer[] {
  const out: CityTransfer[] = [];
  for (let i = 0; i < cities.length - 1; i++) {
    const a = cities[i]!;
    const b = cities[i + 1]!;
    const km = haversineMeters(a.center, b.center) / 1000;
    const mode = suggestMode(km);
    const duration = estimateDurationMin(km, mode);
    out.push({
      from_city: a.name,
      to_city: b.name,
      distance_km: Math.round(km),
      suggested_mode: mode,
      fact: verified<{ distance_km: number; duration_minutes: number; mode: string }>({
        value: { distance_km: Math.round(km), duration_minutes: duration, mode },
        confidence: "low", // 직선거리 기반 추정 — 실 스케줄/요금 미검증
        sources: [
          {
            name: "TripVerify 추정(직선거리 기반)",
            url: "https://tripverify.local/estimate",
            tier: 3,
            retrieved_at: checkedAt,
            excerpt: "좌표 직선거리→수단·시간 추정",
          },
        ],
        verification: { passes_completed: 1, agree_count: 0, checked_at: checkedAt },
      }),
    });
  }
  return out;
}

function suggestMode(km: number): "train" | "car" | "flight" {
  if (km < 80) return "car";
  if (km < 450) return "train";
  return "flight";
}

function estimateDurationMin(km: number, mode: "train" | "car" | "flight"): number {
  switch (mode) {
    case "car":
      return Math.round((km / 70) * 60);
    case "train":
      return Math.round((km / 90) * 60);
    case "flight":
      return Math.round((km / 700) * 60 + 180); // 공항 대기·이동 3시간 오버헤드
  }
}
