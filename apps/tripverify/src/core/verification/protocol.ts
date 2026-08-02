import type { Confidence } from "../types/confidence";

/**
 * 3중 검증 프로토콜의 판정부 인터페이스 (§3).
 * Phase 0 은 계약(입출력 타입)과 순수 판정 함수 `judgeConfidence` 만 확정한다.
 * 실제 다중 Pass 수집·시간차 재조회 오케스트레이션은 Phase 1 에서 구현한다.
 */

export interface JudgeInput {
  /** 서로 동의(허용오차 내)한 독립 출처 수. */
  agree_count: number;
  /** 수치형 FACT 의 편차. 비수치형이면 0/undefined. */
  deviation?: number;
  /** 이 FACT 도메인의 허용오차 (비율/거리). 비수치형이면 undefined. */
  tolerance?: number;
}

/**
 * §3 판정 규칙 (순수 함수):
 *   agree_count >= 3 && (편차 판정 통과) → "high"
 *   agree_count === 2                    → "medium"
 *   그 외                                 → "low"
 */
export function judgeConfidence(input: JudgeInput): Confidence {
  const { agree_count, deviation, tolerance } = input;

  const withinTolerance =
    deviation === undefined || tolerance === undefined
      ? true
      : Math.abs(deviation) <= tolerance;

  if (agree_count >= 3 && withinTolerance) return "high";
  if (agree_count === 2) return "medium";
  return "low";
}
