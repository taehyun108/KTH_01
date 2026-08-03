import type { Confidence, SourceTier, VerificationPass } from "./confidence";

/**
 * VerifiedFact — 사용자에게 노출되는 모든 사실 정보(FACT)의 공통 래퍼 (§4).
 *
 * 절대 원칙(§0):
 *   1. 환각 금지 — 실제로 조회한 값만 담는다.
 *   2. 3중 교차검증 — 독립 출처 3곳 이상. 못 채우면 confidence="low".
 *   3. 출처 필수 — 모든 값에 source_url / name / retrieved_at 동반.
 *   4. 모르면 모른다 — 빈 값은 value=null + unverified_reason.
 *
 * ⭐ 타입 레벨 강제(§4): UI 컴포넌트가 원시값을 직접 받지 못하도록,
 *    VerifiedFact 는 유니크 심볼로 브랜드된다. 팩토리(make-fact.ts)를
 *    거치지 않은 임의 객체는 이 타입에 할당될 수 없다.
 */
declare const VERIFIED_BRAND: unique symbol;

export interface Source {
  /** 출처 표기명 (예: "오사카 관광청 공식"). */
  name: string;
  /** 출처 URL — 필수. 없으면 스키마 파싱 단계에서 거부된다(§0-3). */
  url: string;
  /** 출처 등급 (1=공식, 2=플랫폼, 3=커뮤니티). */
  tier: SourceTier;
  /** 조회 시각 ISO8601. */
  retrieved_at: string;
  /** 근거 문장 (30자 이내). */
  excerpt?: string;
}

export interface Verification {
  /** 완료한 Pass 수 (1~3). */
  passes_completed: VerificationPass;
  /** 서로 동의한 독립 출처 수. */
  agree_count: number;
  /** 수치형 FACT의 편차 (허용오차 판정용). */
  deviation?: number;
  /** 채택하지 않은 상충 값들 — UI에서 펼쳐볼 수 있게 보관(§3). */
  conflicting_values?: ConflictingValue[];
  /** 검증 판정 시각 ISO8601. */
  checked_at: string;
}

export interface ConflictingValue {
  value: unknown;
  source: Source;
}

export interface VerifiedFact<T> {
  /** 브랜드 — 팩토리 외부에서 생성한 객체의 할당을 차단하는 phantom 필드. */
  readonly [VERIFIED_BRAND]: true;
  /** 검증 통과 값. 모르면 null(§0-4). */
  value: T | null;
  confidence: Confidence;
  /** 근거 출처들. value 가 있으면 최소 1개(스키마 강제). */
  sources: Source[];
  verification: Verification;
  /** value===null 일 때 반드시 채운다(§0-4). */
  unverified_reason?: string;
}

/**
 * UI가 값을 렌더링하기 전에 반드시 통과해야 하는 타입 가드.
 * confidence="low" 는 값 자체를 숨겨야 하므로(§3) high|medium 만 값 노출을 허용한다.
 */
export function isRenderable<T>(
  fact: VerifiedFact<T>,
): fact is VerifiedFact<T> & { value: T; confidence: "high" | "medium" } {
  return fact.value !== null && fact.confidence !== "low";
}

/**
 * 실제 출처가 있는 값인지 — 일정에 '표시 가능'한지 판별한다.
 * value 가 있고 출처가 1곳 이상이면 참(§0: 출처 있는 실제 조회 데이터).
 * confidence 가 low 여도, 실존을 뒷받침하는 출처가 있으면 배지를 달아 노출한다.
 * (값이 null 인 완전 미확인 항목만 숨긴다 → 유령 장소 0건은 유지)
 */
export function hasSourcedValue<T>(
  fact: VerifiedFact<T>,
): fact is VerifiedFact<T> & { value: T } {
  return fact.value !== null && fact.sources.length > 0;
}

/** 브랜드를 제거한 순수 데이터 형태 — 직렬화(JSON 저장/전송)용. */
export type PlainFact<T> = Omit<VerifiedFact<T>, typeof VERIFIED_BRAND>;
