"use client";
import type { Itinerary } from "@/core/types/itinerary";
import { naverSearch, instagramTag } from "@/lib/format";

/**
 * 요즘 뜨는 곳(핫플) — 네이버/인스타 실시간 검색 링크.
 * 트렌디한 핫플 데이터는 무료 검증 소스가 없어(§0 지어내지 않음) 최신 후기·사진을
 * 바로 볼 수 있는 검색 링크로 제공한다.
 */
export function HotspotLinks({ itinerary }: { itinerary: Itinerary }) {
  const cities = itinerary.cities.length
    ? itinerary.cities.map((c) => c.name)
    : itinerary.query.destinations;
  if (cities.length === 0) return null;

  return (
    <div className="rounded-lg border border-pink-200 bg-pink-50/50 p-4 dark:border-pink-900 dark:bg-pink-950/20">
      <h3 className="font-semibold">🔥 요즘 뜨는 곳 (실시간 핫플·후기)</h3>
      <p className="mt-1 text-xs opacity-60">
        일정은 검증된 명소 위주입니다. 최신 트렌드·핫플·맛집은 아래에서 확인하세요.
      </p>
      <div className="mt-3 space-y-2 text-sm">
        {cities.map((city) => (
          <div key={city} className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs opacity-80">{city}</span>
            <div className="flex flex-wrap gap-1.5">
              <Chip href={naverSearch(`${city} 핫플`)} label="네이버 핫플" />
              <Chip href={naverSearch(`${city} 가볼만한곳`)} label="가볼만한곳" />
              <Chip href={naverSearch(`${city} 맛집`)} label="맛집" />
              <Chip href={instagramTag(`${city}여행`)} label="인스타 태그" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
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
