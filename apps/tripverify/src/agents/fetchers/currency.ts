import "server-only";
import type { CurrencyInfo } from "@/core/types/domains";
import type { Observation } from "@/core/verification/observation";
import type { SourceReader } from "../types";
import { fetchJson, nowISO } from "@/lib/http";

export interface CurrencyArgs {
  code: string; // ISO 4217, 예: "JPY"
}

/**
 * 키 불필요 환율 소스 3종 (§5 폴백 조합).
 * 서로 다른 운영사/도메인이라 독립 교차검증이 가능하다.
 * 키(KOREAEXIM 등)가 있으면 상위 티어 소스를 추가로 붙일 수 있다.
 */

/** frankfurter.dev — ECB 공시 기반 (tier 1). */
export const frankfurterReader: SourceReader<CurrencyArgs, CurrencyInfo> = async ({
  code,
}) => {
  const data = await fetchJson<{ rates: Record<string, number> }>(
    `https://api.frankfurter.dev/v1/latest?base=${code}&symbols=KRW`,
  );
  return [obs(code, data.rates.KRW, {
    name: "Frankfurter (ECB)",
    url: "https://api.frankfurter.dev/",
    tier: 1,
  })];
};

/** exchangerate.host (tier 2). */
export const exchangerateHostReader: SourceReader<CurrencyArgs, CurrencyInfo> = async ({
  code,
}) => {
  const data = await fetchJson<{ rates: Record<string, number> }>(
    `https://api.exchangerate.host/latest?base=${code}&symbols=KRW`,
  );
  return [obs(code, data.rates.KRW, {
    name: "exchangerate.host",
    url: "https://exchangerate.host/",
    tier: 2,
  })];
};

/** open.er-api.com (tier 2). */
export const erApiReader: SourceReader<CurrencyArgs, CurrencyInfo> = async ({ code }) => {
  const data = await fetchJson<{ rates: Record<string, number> }>(
    `https://open.er-api.com/v6/latest/${code}`,
  );
  return [obs(code, data.rates.KRW, {
    name: "open.er-api.com",
    url: "https://open.er-api.com/",
    tier: 2,
  })];
};

export const liveCurrencyReaders: SourceReader<CurrencyArgs, CurrencyInfo>[] = [
  frankfurterReader,
  exchangerateHostReader,
  erApiReader,
];

function obs(
  code: string,
  krwPerUnit: number | undefined,
  source: { name: string; url: string; tier: 1 | 2 | 3 },
): Observation<CurrencyInfo> {
  if (typeof krwPerUnit !== "number" || !Number.isFinite(krwPerUnit)) {
    throw new Error(`${source.name}: KRW 환율 없음`);
  }
  return {
    value: { code, krw_per_unit: krwPerUnit, base: "KRW" },
    source: { ...source, retrieved_at: nowISO() },
    pass: source.tier === 1 ? 1 : 2,
  };
}
