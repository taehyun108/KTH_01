"use client";
import type { Itinerary } from "@/core/types/itinerary";
import {
  googleFlights,
  skyscannerSearch,
  naverFlight,
  googleFlightsByAirline,
  DEPARTURE_AIRLINES,
} from "@/lib/format";

/**
 * 항공편 — 무료 키 없이 실시간 시각/가격을 조회할 수 있는 검색 링크.
 * (무료로 검증 가능한 항공 스케줄 공개 API 가 없어 값을 지어내지 않고 링크로 제공, §0)
 * 항공사별(대한항공/아시아나/Air Japan 등) 검색도 제공 — 해당 항공사가 그 노선을
 * 운항하지 않으면 결과가 비므로 정직한 검색 링크다.
 */
export function FlightLinks({ itinerary }: { itinerary: Itinerary }) {
  const { query } = itinerary;
  const origin = query.origin;
  const first = query.destinations[0] ?? "";
  const last = query.destinations[query.destinations.length - 1] ?? first;

  return (
    <div className="rounded-lg border border-black/10 p-4 dark:border-white/10">
      <h3 className="font-semibold">✈️ 항공편</h3>
      <p className="mt-1 text-xs opacity-60">
        실시간 시각·가격은 아래에서 확인하세요(무료). 검증 가능한 무료 항공 API 가 없어
        시각을 임의로 넣지 않습니다.
      </p>
      <div className="mt-3 space-y-2 text-sm">
        <Row label={`가는 편  ${origin} → ${first}  (${query.start_date})`}>
          <LinkChip href={googleFlights(origin, first, query.start_date)} label="구글항공권" />
          <LinkChip href={skyscannerSearch(origin, first)} label="스카이스캐너" />
          <LinkChip href={naverFlight()} label="네이버항공권" />
        </Row>
        <Row label={`오는 편  ${last} → ${origin}  (${query.end_date})`}>
          <LinkChip href={googleFlights(last, origin, query.end_date)} label="구글항공권" />
          <LinkChip href={skyscannerSearch(last, origin)} label="스카이스캐너" />
          <LinkChip href={naverFlight()} label="네이버항공권" />
        </Row>
      </div>

      <details className="mt-3">
        <summary className="cursor-pointer text-xs font-medium opacity-80">
          항공사별 편 검색 (대한항공 · 아시아나 · Air Japan 등) ▾
        </summary>
        <div className="mt-2 space-y-3">
          <AirlineGrid
            label={`가는 편  ${origin} → ${first}`}
            origin={origin}
            dest={first}
            date={query.start_date}
          />
          <AirlineGrid
            label={`오는 편  ${last} → ${origin}`}
            origin={last}
            dest={origin}
            date={query.end_date}
          />
        </div>
      </details>
    </div>
  );
}

function AirlineGrid({
  label,
  origin,
  dest,
  date,
}: {
  label: string;
  origin: string;
  dest: string;
  date: string;
}) {
  return (
    <div>
      <div className="text-xs opacity-70">{label}</div>
      <div className="mt-1 flex flex-wrap gap-1.5">
        {DEPARTURE_AIRLINES.map((a) => (
          <LinkChip
            key={a.en}
            href={googleFlightsByAirline(origin, dest, date, a.en)}
            label={a.ko}
          />
        ))}
      </div>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <span className="text-xs opacity-80">{label}</span>
      <div className="flex gap-1.5">{children}</div>
    </div>
  );
}

function LinkChip({ href, label }: { href: string; label: string }) {
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
