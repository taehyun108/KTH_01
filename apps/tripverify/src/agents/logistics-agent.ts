import type { LogisticsInfo } from "@/core/types/domains";
import type { VerifiedFact } from "@/core/types/verified-fact";
import type { Comparator } from "@/core/verification/observation";
import type { SourceReader } from "./types";
import type { LogisticsArgs } from "./fetchers/logistics";
import { verify } from "@/core/verification/verifier";
import { unverified } from "@/core/factory/make-fact";

/** 공휴일 목록 완전 일치 비교자(정렬된 배열 비교). */
const holidaysComparator: Comparator<LogisticsInfo> = {
  agree: (a, b) =>
    JSON.stringify(a.public_holidays ?? []) === JSON.stringify(b.public_holidays ?? []),
  deviation: () => 0,
};

/**
 * logistics-agent (§2). 여러 공휴일 소스를 교차검증한다.
 * 비자/콘센트/eSIM 은 신뢰 가능한 키불필요 API 가 없어 채우지 않고,
 * planner 이후 verifier 재조사 또는 키 소스로 보강한다(§0 정직성).
 */
export async function logisticsAgent(
  args: LogisticsArgs,
  readers: SourceReader<LogisticsArgs, LogisticsInfo>[],
): Promise<VerifiedFact<LogisticsInfo>> {
  const settled = await Promise.allSettled(readers.map((r) => r(args)));
  const obs = settled.flatMap((s) => (s.status === "fulfilled" ? s.value : []));

  if (obs.length === 0) {
    return unverified<LogisticsInfo>("공휴일/입국정보 출처를 조회하지 못함");
  }

  return verify<LogisticsInfo>(obs, { comparator: holidaysComparator });
}
