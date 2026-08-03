import "server-only";
import Holidays from "date-holidays";
import type { LogisticsInfo } from "@/core/types/domains";
import type { Observation } from "@/core/verification/observation";
import type { SourceReader } from "../types";
import type { LogisticsArgs } from "../fetchers/logistics";

/**
 * date-holidays 오프라인 공휴일 리더 (§5 폴백, 무료·무네트워크).
 * 공식 규칙 기반의 권위 있는 오프라인 데이터셋 → tier 2 소스로 취급.
 * 온라인 소스(Nager/OpenHolidays)와 함께 쓰면 독립 3소스 교차검증이 가능해진다.
 */
export const dateHolidaysReader: SourceReader<LogisticsArgs, LogisticsInfo> = async (args) => {
  let list: string[];
  try {
    const hd = new Holidays(args.country_code);
    list = hd
      .getHolidays(args.year)
      .filter((h) => h.type === "public")
      .map((h) => h.date.slice(0, 10)); // "YYYY-MM-DD HH:mm:ss" → "YYYY-MM-DD"
  } catch {
    return [];
  }
  const holidays = filterRange(list, args);
  return [
    {
      value: { public_holidays: holidays },
      source: {
        name: "date-holidays (오프라인)",
        url: "https://github.com/commenthol/date-holidays",
        tier: 2,
        retrieved_at: new Date().toISOString(),
      },
      pass: 3,
    } satisfies Observation<LogisticsInfo>,
  ];
};

function filterRange(dates: string[], args: LogisticsArgs): string[] {
  const uniq = [...new Set(dates)].sort();
  if (!args.start_date || !args.end_date) return uniq;
  const s = Date.parse(args.start_date);
  const e = Date.parse(args.end_date);
  return uniq.filter((d) => {
    const t = Date.parse(d);
    return t >= s && t <= e;
  });
}
