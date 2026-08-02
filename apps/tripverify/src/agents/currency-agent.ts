import type { CurrencyInfo } from "@/core/types/domains";
import type { VerifiedFact } from "@/core/types/verified-fact";
import type { SourceReader } from "./types";
import type { CurrencyArgs } from "./fetchers/currency";
import { verify } from "@/core/verification/verifier";
import { numericRatioOn } from "@/core/verification/observation";
import { TOLERANCE } from "@/core/verification/tolerance";
import { unverified } from "@/core/factory/make-fact";

/**
 * currency-agent (§2). 여러 독립 환율 소스의 관측을 수집만 하고,
 * 판정은 verifier(3중 검증)에 위임한다. 환율은 변동 데이터이므로
 * Pass 3(시간차 재조회)을 요구한다.
 */
export async function currencyAgent(
  args: CurrencyArgs,
  readers: SourceReader<CurrencyArgs, CurrencyInfo>[],
): Promise<VerifiedFact<CurrencyInfo>> {
  const settled = await Promise.allSettled(readers.map((r) => r(args)));
  const observations = settled.flatMap((s) =>
    s.status === "fulfilled" ? s.value : [],
  );

  if (observations.length === 0) {
    return unverified<CurrencyInfo>("환율 출처를 하나도 조회하지 못함");
  }

  return verify<CurrencyInfo>(observations, {
    comparator: numericRatioOn(TOLERANCE.fx_rate_ratio, (c) => c.krw_per_unit),
    tolerance: TOLERANCE.fx_rate_ratio,
    requireTimeSeparation: true,
  });
}
