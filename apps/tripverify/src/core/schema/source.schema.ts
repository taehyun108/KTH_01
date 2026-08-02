import { z } from "zod";

/** ISO8601 (오프셋 허용). retrieved_at / checked_at 공통. */
export const iso8601 = z.iso.datetime({ offset: true });

/**
 * Source 스키마 (§0-3, §4).
 * url 이 유효한 URL 이 아니면 파싱 실패 → 출처 없는 값은 만들 수 없다.
 */
export const SourceSchema = z.object({
  name: z.string().min(1),
  url: z.url(),
  tier: z.union([z.literal(1), z.literal(2), z.literal(3)]),
  retrieved_at: iso8601,
  excerpt: z.string().max(30, "근거 문구는 30자 이내(§4)").optional(),
});

export type SourceInput = z.infer<typeof SourceSchema>;
