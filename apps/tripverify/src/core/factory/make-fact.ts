import type { z } from "zod";
import type {
  VerifiedFact,
  Source,
  Verification,
  PlainFact,
} from "../types/verified-fact";
import type { Confidence } from "../types/confidence";
import {
  VerifiedFactSchema,
  verifiedFactSchema,
} from "../schema/verified-fact.schema";

/**
 * VerifiedFact 생성의 유일한 경로 (§4).
 * 여기서만 브랜드를 부여하므로, UI/도메인 코드가 임의 객체를
 * VerifiedFact 로 위조할 수 없다. 브랜드 부여 전 항상 Zod 로 불변식을 검증한다.
 */

function nowISO(): string {
  return new Date().toISOString();
}

/** Zod 검증을 통과한 평문 FACT 에 브랜드를 부여한다. */
function brand<T>(plain: PlainFact<T>): VerifiedFact<T> {
  VerifiedFactSchema.parse(plain); // 실패 시 throw — 불변식 위반 객체 차단
  return plain as VerifiedFact<T>;
}

/**
 * 검증 실패/미조회 FACT. §0-4: 반드시 사유를 동반한다.
 * value=null, confidence="low" 로 고정.
 */
export function unverified<T>(reason: string): VerifiedFact<T> {
  return brand<T>({
    value: null,
    confidence: "low",
    sources: [],
    verification: {
      passes_completed: 1,
      agree_count: 0,
      checked_at: nowISO(),
    },
    unverified_reason: reason,
  });
}

/**
 * 검증 통과 FACT. sources/verification 정합성은 스키마가 재검사한다.
 * (confidence≥medium 이면 sources 2개 이상 등 §3 규칙)
 */
export function verified<T>(args: {
  value: T;
  confidence: Confidence;
  sources: Source[];
  verification: Verification;
}): VerifiedFact<T> {
  return brand<T>({ ...args });
}

/**
 * 외부(캐시/DB/네트워크)에서 들어온 평문 객체를 값 스키마로 검증하며 복원한다.
 * 브랜드가 벗겨진 JSON 을 다시 타입 안전한 VerifiedFact 로 승격시키는 유일한 통로.
 */
export function reviveFact<S extends z.ZodTypeAny>(
  valueSchema: S,
  raw: unknown,
): VerifiedFact<z.infer<S>> {
  const parsed = verifiedFactSchema(valueSchema).parse(raw);
  return parsed as VerifiedFact<z.infer<S>>;
}
