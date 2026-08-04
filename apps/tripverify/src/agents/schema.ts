import { z } from "zod";

/** TripQuery 런타임 검증 (§7 Zod). API 경계에서 사용. 다중 도시 + 구성원. */
export const TripQuerySchema = z
  .object({
    origin: z.string().min(1),
    country: z.string().optional(),
    destinations: z.array(z.string().min(1)).min(1).max(6), // 최대 6개 도시
    start_date: z.iso.date(),
    end_date: z.iso.date(),
    party: z.object({
      adults: z.number().int().min(1).max(20),
      children: z.number().int().min(0).max(20),
    }),
    budget_krw: z.number().int().positive().optional(),
    style: z.array(z.enum(["relax", "food", "history", "activity"])).min(1),
    transport: z.array(z.enum(["walk", "transit", "car"])).min(1),
    concept: z.string().max(300).optional(),
  })
  .refine((q) => Date.parse(q.end_date) >= Date.parse(q.start_date), {
    message: "end_date 는 start_date 이후여야 함",
    path: ["end_date"],
  })
  .refine((q) => dayCount(q.start_date, q.end_date) <= 30, {
    message: "여행 기간은 최대 30일",
    path: ["end_date"],
  })
  .refine((q) => dayCount(q.start_date, q.end_date) >= q.destinations.length, {
    message: "도시 수보다 여행 일수가 많아야 함(도시당 최소 1일)",
    path: ["destinations"],
  });

export type TripQueryInput = z.infer<typeof TripQuerySchema>;

export function dayCount(start: string, end: string): number {
  return Math.round((Date.parse(end) - Date.parse(start)) / 86_400_000) + 1;
}

/**
 * 총 일수를 도시들에 균등 배분한다(앞 도시부터 나머지 +1). 도시당 최소 1일.
 * @returns 각 도시의 일수 배열 (합 = totalDays)
 */
export function allocateNights(totalDays: number, cities: number): number[] {
  const base = Math.floor(totalDays / cities);
  const extra = totalDays % cities;
  return Array.from({ length: cities }, (_, i) => base + (i < extra ? 1 : 0));
}
