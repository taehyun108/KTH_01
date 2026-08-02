import type { VerifiedFact, Source, ConflictingValue } from "../types/verified-fact";
import type { Observation, Comparator } from "./observation";
import { verified, unverified } from "../factory/make-fact";
import { judgeConfidence } from "./protocol";
import { rankByTier, isIndependentDomain } from "./tier";
import { PASS3_MIN_INTERVAL_MS } from "./tolerance";

export interface VerifyConfig<T> {
  comparator: Comparator<T>;
  /** 편차 판정 허용오차 (수치형). 비수치형이면 생략. */
  tolerance?: number;
  /**
   * Pass 3(시간차 재조회) 필수 여부. 환율·항공료 등 변동 데이터는 true.
   * 60초 이상 간격의 동의 관측이 없으면 high 로 승격하지 않는다(§3).
   */
  requireTimeSeparation?: boolean;
  minIntervalMs?: number;
  /** 현재 시각 주입(테스트용). */
  now?: () => number;
}

/**
 * 3중 검증 프로토콜 판정부 (§3).
 * 여러 출처 관측을 받아 하나의 VerifiedFact 로 축약한다.
 *
 * 절차:
 *  1) 출처 등급 우선으로 채택값 선정 (다수결 아님 — §3).
 *  2) 채택값에 동의하는 '독립 도메인' 수 = agree_count.
 *  3) 동의 관측의 Pass 다양성 + 시간차(≥60s)로 passes_completed 산정.
 *  4) judgeConfidence 로 confidence 결정, 커뮤니티 단독/시간차 미충족 시 강등.
 *  5) 미채택 값은 conflicting_values 로 보관.
 */
export function verify<T>(
  observations: Observation<T>[],
  config: VerifyConfig<T>,
): VerifiedFact<T> {
  if (observations.length === 0) {
    return unverified<T>("관측된 출처가 없음");
  }

  const { comparator } = config;
  const minInterval = config.minIntervalMs ?? PASS3_MIN_INTERVAL_MS;

  // 1) 출처 등급 우선 채택. 동일 tier 는 '동의 관측이 가장 많은' 값으로 tie-break.
  const ranked = rankByTier(observations.map((o) => ({ ...o, tier: o.source.tier })));
  const adopted = pickAdopted(ranked as Observation<T>[], comparator);

  // 2) 채택값에 동의하는 관측 / 상충 관측 분리
  const agreeing: Observation<T>[] = [];
  const conflicting: ConflictingValue[] = [];
  for (const o of observations) {
    if (comparator.agree(adopted.value, o.value)) agreeing.push(o);
    else conflicting.push({ value: o.value, source: o.source });
  }

  // agree_count = 서로 독립(도메인 상이)인 동의 출처 수
  const agreeCount = countIndependent(agreeing.map((o) => o.source));

  // 3) passes_completed: 동의 관측의 Pass 다양성 + Pass3 시간차 검사
  const passSet = new Set(agreeing.map((o) => o.pass));
  let passesCompleted = Math.max(...[...passSet, 1]) as 1 | 2 | 3;
  const timeSeparated = hasTimeSeparation(agreeing, minInterval);
  if (config.requireTimeSeparation && !timeSeparated) {
    // 시간차 미충족 → Pass3 미완료로 간주
    if (passesCompleted === 3) passesCompleted = 2;
  }

  // 4) 편차(동의 관측 중 최대) + confidence
  const deviation = agreeing.reduce(
    (max, o) => Math.max(max, comparator.deviation(adopted.value, o.value)),
    0,
  );
  let confidence = judgeConfidence(
    config.tolerance !== undefined
      ? { agree_count: agreeCount, deviation, tolerance: config.tolerance }
      : { agree_count: agreeCount },
  );

  // 강등 규칙:
  //  - 변동 데이터인데 시간차(≥60s) 재조회 미충족 → high 불가(§3 Pass3)
  if (confidence === "high" && config.requireTimeSeparation && !timeSeparated) {
    confidence = "medium";
  }
  //  - 커뮤니티(tier3) 단독 근거 → high 불가(§3 단독 채택 금지)
  const hasAuthoritative = agreeing.some((o) => o.source.tier <= 2);
  if (confidence === "high" && !hasAuthoritative) confidence = "medium";

  // confidence 가 medium 이상인데 독립 출처가 부족하면 low 로 안전 강등
  if (confidence !== "low" && agreeCount < 2) confidence = "low";

  const sources = dedupSources(agreeing.map((o) => o.source));

  // low 인데 값이 있으면: §3 값 숨김 대상. 값은 유지하되 사유를 남긴다.
  if (confidence === "low") {
    return verified<T>({
      value: adopted.value,
      confidence: "low",
      sources: sources.length > 0 ? sources : [adopted.source],
      verification: {
        passes_completed: passesCompleted,
        agree_count: agreeCount,
        ...(config.tolerance !== undefined ? { deviation } : {}),
        ...(conflicting.length > 0 ? { conflicting_values: conflicting } : {}),
        checked_at: new Date((config.now ?? Date.now)()).toISOString(),
      },
    });
  }

  return verified<T>({
    value: adopted.value,
    confidence,
    sources,
    verification: {
      passes_completed: passesCompleted,
      agree_count: agreeCount,
      ...(config.tolerance !== undefined ? { deviation } : {}),
      ...(conflicting.length > 0 ? { conflicting_values: conflicting } : {}),
      checked_at: new Date((config.now ?? Date.now)()).toISOString(),
    },
  });
}

/** 등급 우선 + 동의 최다로 채택 관측 선정. */
function pickAdopted<T>(ranked: Observation<T>[], cmp: Comparator<T>): Observation<T> {
  const bestTier = ranked[0]!.source.tier;
  const topTierObs = ranked.filter((o) => o.source.tier === bestTier);
  // 동일 등급 내에서 다른 관측과 가장 많이 동의하는 값을 채택.
  let best = topTierObs[0]!;
  let bestSupport = -1;
  for (const cand of topTierObs) {
    const support = ranked.filter((o) => cmp.agree(cand.value, o.value)).length;
    if (support > bestSupport) {
      best = cand;
      bestSupport = support;
    }
  }
  return best;
}

/** 서로 독립(등록가능 도메인 상이)인 출처 수. */
function countIndependent(sources: Source[]): number {
  const kept: Source[] = [];
  for (const s of sources) {
    if (kept.every((k) => isIndependentDomain(k, s))) kept.push(s);
  }
  return kept.length;
}

/** 동의 관측 중 retrieved_at 이 minInterval 이상 벌어진 쌍이 있는가. */
function hasTimeSeparation<T>(agreeing: Observation<T>[], minInterval: number): boolean {
  const times = agreeing.map((o) => Date.parse(o.source.retrieved_at)).sort((a, b) => a - b);
  if (times.length < 2) return false;
  return times[times.length - 1]! - times[0]! >= minInterval;
}

function dedupSources(sources: Source[]): Source[] {
  const seen = new Set<string>();
  const out: Source[] = [];
  for (const s of rankByTier(sources)) {
    if (seen.has(s.url)) continue;
    seen.add(s.url);
    out.push(s);
  }
  return out;
}
