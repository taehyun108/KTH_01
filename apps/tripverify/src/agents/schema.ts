import { z } from "zod";

/** TripQuery 런타임 검증 (§7 Zod). API 경계에서 사용. */
export const TripQuerySchema = z
  .object({
    origin: z.string().min(1),
    destination: z.string().min(1),
    country: z.string().optional(),
    start_date: z.iso.date(),
    end_date: z.iso.date(),
    travelers: z.number().int().min(1).max(20),
    budget_krw: z.number().int().positive().optional(),
    style: z.array(z.enum(["relax", "food", "history", "activity"])).min(1),
    transport: z.array(z.enum(["walk", "transit", "car"])).min(1),
  })
  .refine((q) => Date.parse(q.end_date) >= Date.parse(q.start_date), {
    message: "end_date 는 start_date 이후여야 함",
    path: ["end_date"],
  })
  .refine((q) => dayCount(q.start_date, q.end_date) <= 21, {
    message: "여행 기간은 최대 21일",
    path: ["end_date"],
  });

export type TripQueryInput = z.infer<typeof TripQuerySchema>;

export function dayCount(start: string, end: string): number {
  return Math.round((Date.parse(end) - Date.parse(start)) / 86_400_000) + 1;
}
