"use client";
import type { ItineraryDay } from "@/core/types/itinerary";
import type { VerifiedFact } from "@/core/types/verified-fact";
import { ConfidenceBadge } from "./ConfidenceBadge";
import {
  minutesLabel,
  weekdayKo,
  googleMapsPlaceAt,
  naverBlogSearch,
  displayName,
  searchName,
} from "@/lib/format";
import { recommendReason, menuHint } from "@/lib/recommend";
import type { Restaurant } from "@/core/types/domains";

const DAY_COLORS = ["#2563eb", "#db2777", "#059669", "#d97706", "#7c3aed", "#0891b2", "#dc2626"];

/** 일정 타임라인 (§8-1). 일자별 카드 + 항목별 신뢰도 배지 + 클릭 시 출처. */
export function Timeline({
  days,
  onSelect,
}: {
  days: ItineraryDay[];
  onSelect: (f: VerifiedFact<unknown>, title: string) => void;
}) {
  return (
    <div className="space-y-4">
      {days.map((day, di) => (
        <div key={di} className="rounded-lg border border-black/10 dark:border-white/10">
          <div
            className="flex items-center justify-between rounded-t-lg px-4 py-2 text-white"
            style={{ background: DAY_COLORS[di % DAY_COLORS.length] }}
          >
            <h3 className="font-semibold">
              Day {di + 1} · {day.city} · {day.date} ({weekdayKo(day.weekday)})
            </h3>
            <span className="text-xs opacity-90">
              활동 {minutesLabel(day.total_activity_minutes)} · 이동{" "}
              {minutesLabel(day.total_travel_minutes)} ({Math.round(day.travel_ratio * 100)}%)
            </span>
          </div>

          <ol className="divide-y divide-black/5 dark:divide-white/5">
            {day.items.length === 0 && (
              <li className="px-4 py-3 text-sm opacity-60">
                검증된 일정 항목이 없습니다.
              </li>
            )}
            {day.items.map((item, ii) => (
              <li key={ii} className="px-4 py-3">
                {item.travel_from_prev && item.travel_from_prev.minutes > 0 && (
                  <div className="mb-1 text-xs opacity-60">
                    ↓ {item.travel_from_prev.mode} {minutesLabel(item.travel_from_prev.minutes)}
                    {item.travel_from_prev.estimated ? " (추정)" : ""} · {item.travel_from_prev.source_name}
                  </div>
                )}
                {(() => {
                  const disp = displayName(item.place.value) || item.name;
                  const sname = searchName(item.place.value) || item.name;
                  const loc = item.place.value?.location;
                  const mapHref = loc
                    ? googleMapsPlaceAt(sname, { lat: loc.lat, lng: loc.lng })
                    : `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(sname)}`;
                  const reason = recommendReason(item.place.value, item.kind, item.place.confidence);
                  const menu = item.kind === "food" ? menuHint(item.place.value as Restaurant | null) : null;
                  return (
                    <>
                    <div className="flex items-center justify-between gap-2">
                      <div className="min-w-0">
                        <span className="mr-2 text-sm tabular-nums opacity-70">
                          {item.start}–{item.end}
                        </span>
                        <a
                          href={mapHref}
                          target="_blank"
                          rel="noreferrer"
                          className="font-medium hover:underline"
                          title="구글지도에서 보기(정확한 위치)"
                        >
                          {item.kind === "food" ? "🍽 " : "📍 "}
                          {disp}
                        </a>
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        <a
                          href={naverBlogSearch(`${sname} ${day.city}`)}
                          target="_blank"
                          rel="noreferrer"
                          className="text-xs opacity-60 hover:opacity-100"
                          title="네이버 블로그 최신 후기"
                        >
                          📝후기
                        </a>
                        <button onClick={() => onSelect(item.place, disp)} title="출처·검증 보기">
                          <ConfidenceBadge confidence={item.place.confidence} />
                        </button>
                      </div>
                    </div>
                    {reason && (
                      <div className="mt-1 text-xs opacity-70">💡 {reason}</div>
                    )}
                    {item.kind === "food" && menu && (
                      <div className="mt-0.5 text-xs opacity-70">
                        🍜 추천 메뉴(요리 종류): {menu} ·{" "}
                        <a
                          href={naverBlogSearch(`${sname} 메뉴`)}
                          target="_blank"
                          rel="noreferrer"
                          className="underline"
                        >
                          메뉴 검색
                        </a>
                      </div>
                    )}
                    </>
                  );
                })()}
              </li>
            ))}
          </ol>

          {day.warnings.length > 0 && (
            <ul className="rounded-b-lg bg-amber-50 px-4 py-2 text-xs text-amber-800 dark:bg-amber-950/30 dark:text-amber-300">
              {day.warnings.map((w, wi) => (
                <li key={wi}>⚠ {w}</li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </div>
  );
}

export { DAY_COLORS };
