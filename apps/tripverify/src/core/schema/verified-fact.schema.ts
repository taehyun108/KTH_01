import { z } from "zod";
import { SourceSchema, iso8601 } from "./source.schema";

/**
 * VerifiedFact 의 런타임 스키마 (§4). 타입(verified-fact.ts)과 1:1 대응하며,
 * 팩토리(make-fact.ts)는 브랜드를 붙이기 전에 이 스키마로 불변식을 강제한다.
 *
 * 강제하는 불변식:
 *   - sources[].url 누락 → 실패 (출처 필수, §0-3)
 *   - value===null 인데 unverified_reason 없음 → 실패 (§0-4)
 *   - confidence!=="low" 인데 sources.length < 2 → 실패 (§3 판정규칙 정합)
 *   - value!==null 인데 sources 가 비어 있음 → 실패 (출처 없는 값 렌더 금지)
 */

const ConflictingValueSchema = z.object({
  value: z.unknown(),
  source: SourceSchema,
});

const VerificationSchema = z.object({
  passes_completed: z.union([z.literal(1), z.literal(2), z.literal(3)]),
  agree_count: z.number().int().min(0),
  deviation: z.number().optional(),
  conflicting_values: z.array(ConflictingValueSchema).optional(),
  checked_at: iso8601,
});

const ConfidenceSchema = z.enum(["high", "medium", "low"]);

/**
 * value 스키마를 받아 구체적 VerifiedFact 스키마를 만든다.
 * @param valueSchema  FACT 값 T 의 Zod 스키마 (기본: unknown)
 */
/** superRefine 콜백에서 참조하는 공통 형태(제네릭 value 는 unknown 으로 취급). */
interface FactShape {
  value: unknown;
  confidence: z.infer<typeof ConfidenceSchema>;
  sources: z.infer<typeof SourceSchema>[];
  unverified_reason?: string;
}

export function verifiedFactSchema<S extends z.ZodTypeAny>(
  valueSchema: S = z.unknown() as unknown as S,
) {
  return z
    .object({
      value: valueSchema.nullable(),
      confidence: ConfidenceSchema,
      sources: z.array(SourceSchema),
      verification: VerificationSchema,
      unverified_reason: z.string().min(1).optional(),
    })
    .superRefine((raw, ctx) => {
      const fact = raw as unknown as FactShape;
      // §0-4: 값이 없으면 사유가 있어야 한다.
      if (fact.value === null && !fact.unverified_reason) {
        ctx.addIssue({
          code: "custom",
          path: ["unverified_reason"],
          message: "value=null 이면 unverified_reason 필수(§0-4)",
        });
      }
      // 출처 없는 값은 렌더 금지(§0-3).
      if (fact.value !== null && fact.sources.length < 1) {
        ctx.addIssue({
          code: "custom",
          path: ["sources"],
          message: "값이 있으면 출처가 최소 1개 필요(§0-3)",
        });
      }
      // §3: medium 이상은 독립 출처 2개 이상이어야 한다.
      if (fact.confidence !== "low" && fact.sources.length < 2) {
        ctx.addIssue({
          code: "custom",
          path: ["sources"],
          message: "confidence≥medium 은 독립 출처 2개 이상 필요(§3)",
        });
      }
    });
}

/** 기본(값 unknown) 스키마 — 팩토리의 브랜드 전 런타임 검증에 사용. */
export const VerifiedFactSchema = verifiedFactSchema();
