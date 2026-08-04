"use client";
import type { Itinerary } from "@/core/types/itinerary";
import { bookingSearch, tripComSearch, agodaSearch, googleHotels } from "@/lib/format";

/**
 * 숙박 — 트립닷컴/부킹/아고다/구글호텔 실시간 요금 검색(도시·날짜 프리필).
 * 무료로 검증 가능한 숙박요금 API 가 없어 예산의 숙박은 '추정'이며, 실제 요금은
 * 아래 링크에서 확인한다(§0 — 요금을 지어내지 않음).
 */
export function LodgingLinks({ itinerary }: { itinerary: Itinerary }) {
  const adults = itinerary.query.party.adults;

  // 도시별 체크인/체크아웃(해당 도시 첫날~마지막날+1)
  const byCity = new Map<string, string[]>();
  for (const d of itinerary.days) {
    const arr = byCity.get(d.city) ?? [];
    arr.push(d.date);
    byCity.set(d.city, arr);
  }
  const rows = [...byCity.entries()].map(([city, dates]) => {
    const sorted = [...dates].sort();
    const checkin = sorted[0]!;
    const checkout = addDay(sorted[sorted.length - 1]!);
    return { city, checkin, checkout };
  });

  if (rows.length === 0) return null;

  return (
    <div className="rounded-lg border border-black/10 p-4 dark:border-white/10">
      <h3 className="font-semibold">🏨 숙박 (실시간 요금 검색)</h3>
      <p className="mt-1 text-xs opacity-60">
        예산의 숙박은 추정치입니다. 실제 요금·예약은 아래에서 확인하세요(무료).
      </p>
      <div className="mt-3 space-y-2 text-sm">
        {rows.map((r) => (
          <div key={r.city} className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs opacity-80">
              {r.city} · {r.checkin} ~ {r.checkout}
            </span>
            <div className="flex flex-wrap gap-1.5">
              <Chip href={tripComSearch(r.city, r.checkin, r.checkout)} label="트립닷컴" />
              <Chip href={bookingSearch(r.city, r.checkin, r.checkout, adults)} label="부킹닷컴" />
              <Chip href={agodaSearch(r.city)} label="아고다" />
              <Chip href={googleHotels(r.city, r.checkin)} label="구글호텔" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function addDay(date: string): string {
  return new Date(Date.parse(date) + 86_400_000).toISOString().slice(0, 10);
}

function Chip({ href, label }: { href: string; label: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="rounded-full border border-black/10 px-2.5 py-1 text-xs hover:bg-black/5 dark:border-white/10 dark:hover:bg-white/5"
    >
      {label} ↗
    </a>
  );
}
