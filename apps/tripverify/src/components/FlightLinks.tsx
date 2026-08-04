"use client";
import type { Itinerary } from "@/core/types/itinerary";
import { googleFlights, skyscannerSearch, naverFlight } from "@/lib/format";

/**
 * 항공편 — 무료 키 없이 실시간 시각/가격을 조회할 수 있는 검색 링크.
 * (무료로 검증 가능한 항공 스케줄 공개 API 가 없어 값을 지어내지 않고 링크로 제공, §0)
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
