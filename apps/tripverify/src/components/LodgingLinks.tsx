"use client";
import type { Itinerary } from "@/core/types/itinerary";
import type { LatLng } from "@/lib/format";
import { bookingSearch, tripComSearch, agodaSearch, googleHotels } from "@/lib/format";

/**
 * 숙박 — 트립닷컴/부킹/아고다/구글호텔 실시간 요금 검색(도시·날짜 프리필).
 * 무료로 검증 가능한 숙박요금 API 가 없어 예산의 숙박은 '추정'이며, 실제 요금은
 * 아래 링크에서 확인한다(§0 — 요금을 지어내지 않음).
 *
 * 부킹닷컴 링크는 그 도시 일정(동선)의 중심 좌표 + '리뷰 좋은 순' 정렬을 걸어,
 * 동선 근처의 리뷰 좋은(가성비 판단 쉬운) 숙소가 먼저 보이도록 한다.
 */
export function LodgingLinks({ itinerary }: { itinerary: Itinerary }) {
  const adults = itinerary.query.party.adults;

  // 도시 중심 좌표(폴백): cities → destination_center
  const cityCenter = new Map<string, LatLng>();
  for (const c of itinerary.cities) cityCenter.set(c.name, c.center);

  // 도시별 체크인/체크아웃(해당 도시 첫날~마지막날+1) + 동선 중심(방문지 평균 좌표)
  const byCity = new Map<string, { dates: string[]; pts: LatLng[] }>();
  for (const d of itinerary.days) {
    const rec = byCity.get(d.city) ?? { dates: [], pts: [] };
    rec.dates.push(d.date);
    for (const it of d.items) {
      const loc = it.place.value?.location;
      if (loc) rec.pts.push(loc);
    }
    byCity.set(d.city, rec);
  }
  const rows = [...byCity.entries()].map(([city, rec]) => {
    const sorted = [...rec.dates].sort();
    const checkin = sorted[0]!;
    const checkout = addDay(sorted[sorted.length - 1]!);
    const center = centroid(rec.pts) ?? cityCenter.get(city) ?? itinerary.destination_center;
    return { city, checkin, checkout, center };
  });

  if (rows.length === 0) return null;

  return (
    <div className="rounded-lg border border-black/10 p-4 dark:border-white/10">
      <h3 className="font-semibold">🏨 숙박 (동선 근처·리뷰 좋은 순)</h3>
      <p className="mt-1 text-xs opacity-60">
        부킹닷컴은 그날 동선 중심 좌표 + 리뷰 좋은 순으로 정렬됩니다. 예산의 숙박은
        추정치이며, 실제 요금·예약은 아래에서 확인하세요(무료).
      </p>
      <div className="mt-3 space-y-2 text-sm">
        {rows.map((r) => (
          <div key={r.city} className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs opacity-80">
              {r.city} · {r.checkin} ~ {r.checkout}
            </span>
            <div className="flex flex-wrap gap-1.5">
              <Chip
                href={bookingSearch(r.city, r.checkin, r.checkout, adults, r.center)}
                label="부킹닷컴 · 동선/리뷰순"
              />
              <Chip href={tripComSearch(r.city, r.checkin, r.checkout)} label="트립닷컴" />
              <Chip href={agodaSearch(r.city)} label="아고다" />
              <Chip href={googleHotels(r.city, r.checkin)} label="구글호텔" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/** 방문지 좌표들의 평균(동선 중심). 없으면 null. */
function centroid(pts: LatLng[]): LatLng | null {
  if (pts.length === 0) return null;
  const sum = pts.reduce((a, p) => ({ lat: a.lat + p.lat, lng: a.lng + p.lng }), { lat: 0, lng: 0 });
  return { lat: sum.lat / pts.length, lng: sum.lng / pts.length };
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
