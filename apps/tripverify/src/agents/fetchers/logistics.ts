import "server-only";
import type { LogisticsInfo } from "@/core/types/domains";
import type { Observation } from "@/core/verification/observation";
import type { SourceReader } from "../types";
import { fetchJson, nowISO } from "@/lib/http";

export interface LogisticsArgs {
  country_code: string; // ISO2
  year: number;
  /** 여행 기간과 겹치는 공휴일만 남기기 위한 범위(선택). */
  start_date?: string;
  end_date?: string;
}

/** Nager.Date 공휴일 (키 불필요, tier 2). */
export const nagerHolidaysReader: SourceReader<LogisticsArgs, LogisticsInfo> = async (args) => {
  const data = await fetchJson<{ date: string }[]>(
    `https://date.nager.at/api/v3/PublicHolidays/${args.year}/${args.country_code}`,
  );
  const holidays = filterRange(data.map((h) => h.date), args);
  return [wrap(holidays, {
    name: "Nager.Date",
    url: "https://date.nager.at/",
    tier: 2,
  })];
};

/** OpenHolidays API (키 불필요, tier 2, 독립 도메인). */
export const openHolidaysReader: SourceReader<LogisticsArgs, LogisticsInfo> = async (args) => {
  const from = args.start_date ?? `${args.year}-01-01`;
  const to = args.end_date ?? `${args.year}-12-31`;
  const data = await fetchJson<{ startDate: string }[]>(
    `https://openholidaysapi.org/PublicHolidays?countryIsoCode=${args.country_code}` +
      `&validFrom=${from}&validTo=${to}&languageIsoCode=EN`,
  );
  const holidays = filterRange(data.map((h) => h.startDate), args);
  return [wrap(holidays, {
    name: "OpenHolidays API",
    url: "https://www.openholidaysapi.org/",
    tier: 2,
  })];
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

function wrap(
  holidays: string[],
  source: { name: string; url: string; tier: 1 | 2 | 3 },
): Observation<LogisticsInfo> {
  return {
    // 비자/콘센트/eSIM 은 신뢰 가능한 키불필요 소스가 없어 이 리더에서 채우지 않는다(§0-4).
    value: { public_holidays: holidays },
    source: { ...source, retrieved_at: nowISO() },
    pass: source.name === "Nager.Date" ? 1 : 2,
  };
}

export const liveLogisticsReaders: SourceReader<LogisticsArgs, LogisticsInfo>[] = [
  nagerHolidaysReader,
  openHolidaysReader,
];
