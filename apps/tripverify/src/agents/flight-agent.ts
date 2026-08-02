import type { FlightOption } from "@/core/types/domains";
import type { VerifiedFact } from "@/core/types/verified-fact";
import type { Comparator, Observation } from "@/core/verification/observation";
import type { SourceReader } from "./types";
import type { FlightArgs } from "./fetchers/flights";
import { verify } from "@/core/verification/verifier";
import { TOLERANCE } from "@/core/verification/tolerance";
import { unverified } from "@/core/factory/make-fact";

/**
 * 항공편 비교자: 동일 편명 + 출도착 시각 일치 + 가격 ±15%(§3).
 * 가격은 "조회 시점 기준" 라벨이 필수인 변동 데이터.
 */
const flightComparator: Comparator<FlightOption> = {
  agree: (a, b) => {
    if (a.flight_no !== b.flight_no) return false;
    if (a.depart_local !== b.depart_local || a.arrive_local !== b.arrive_local) return false;
    const pa = a.price_estimate_krw;
    const pb = b.price_estimate_krw;
    if (pa === undefined || pb === undefined) return true;
    return Math.abs(pa - pb) / Math.max(pa, pb, 1) <= TOLERANCE.flight_price_ratio;
  },
  deviation: (adopted, other) => {
    const pa = adopted.price_estimate_krw;
    const pb = other.price_estimate_krw;
    if (pa === undefined || pb === undefined) return 0;
    return Math.abs(pa - pb) / Math.max(pa, pb, 1);
  },
};

/**
 * flight-agent (§2). 편명별로 관측을 묶어 교차검증한다. 가격은 변동 데이터이므로
 * Pass 3(시간차)을 요구. 키가 없어 관측이 없으면 unverified 로 정직하게 비운다(§0).
 */
export async function flightAgent(
  args: FlightArgs,
  readers: SourceReader<FlightArgs, FlightOption>[],
): Promise<VerifiedFact<FlightOption>[]> {
  const settled = await Promise.allSettled(readers.map((r) => r(args)));
  const all = settled.flatMap((s) => (s.status === "fulfilled" ? s.value : []));

  if (all.length === 0) {
    return [
      unverified<FlightOption>(
        "항공 스케줄 출처 없음(키 미설정). 키 없는 신뢰 소스가 없어 추정하지 않음.",
      ),
    ];
  }

  const byFlight = new Map<string, Observation<FlightOption>[]>();
  for (const o of all) {
    const arr = byFlight.get(o.value.flight_no) ?? [];
    arr.push(o);
    byFlight.set(o.value.flight_no, arr);
  }

  return [...byFlight.values()].map((obs) =>
    verify<FlightOption>(obs, {
      comparator: flightComparator,
      tolerance: TOLERANCE.flight_price_ratio,
      requireTimeSeparation: true,
    }),
  );
}
