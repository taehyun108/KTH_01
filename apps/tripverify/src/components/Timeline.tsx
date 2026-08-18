"use client";
import type { Itinerary, ItineraryDay } from "@/core/types/itinerary";
import type { VerifiedFact } from "@/core/types/verified-fact";
import type { LatLng } from "@/lib/format";
import { ConfidenceBadge } from "./ConfidenceBadge";
import {
  minutesLabel,
  weekdayKo,
  googleMapsPlaceAt,
  naverBlogSearch,
  displayName,
  searchName,
  bookingSearch,
} from "@/lib/format";
import { recommendReason, menuHint, localeMenu } from "@/lib/recommend";
import type { Restaurant } from "@/core/types/domains";

const DAY_COLORS = ["#2563eb", "#db2777", "#059669", "#d97706", "#7c3aed", "#0891b2", "#dc2626"];

/** 일정 타임라인 (§8-1). 일자별 카드 + 항목별 신뢰도 배지 + 클릭 시 출처. */
export function Timeline({
  itinerary,
  onSelect,
}: {
  itinerary: Itinerary;
  onSelect: (f: VerifiedFact<unknown>, title: string) => void;
}) {
  const days = itinerary.days;
  const adults = itinerary.query.party.adults;
  const cityCenter = new Map(itinerary.cities.map((c) => [c.name, c.center] as const));
  const lodgingByCity = new Map(itinerary.lodging.map((l) => [l.city, l.options] as const));
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
                  // 한국인 여행자 기준 추천 메뉴: 요리 종류 대표 메뉴 → 없으면 지역 명물
                  const menu =
                    item.kind === "food"
                      ? menuHint(item.place.value as Restaurant | null) ?? localeMenu(day.city)
                      : null;
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
                        🍜 한국인 추천 메뉴: {menu} ·{" "}
                        <a
                          href={naverBlogSearch(`${sname} ${day.city} 메뉴 추천`)}
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
            {(() => {
              // 동선 마지막: 그날 방문지 중심(동선 중심) 근처 '실존' 호텔(OSM) 추천 + 요금검색
              const pts = day.items.map((it) => it.place.value?.location).filter((l): l is LatLng => !!l);
              const center = centroid(pts) ?? cityCenter.get(day.city);
              const checkin = day.date;
              const checkout = addDay(day.date);
              const searchHref = bookingSearch(day.city, checkin, checkout, adults, center);
              // 그날 동선 중심에 가까운 순으로 실존 호텔 상위 3곳
              const all = lodgingByCity.get(day.city) ?? [];
              const picks = center
                ? [...all]
                    .filter((h) => h.value)
                    .sort(
                      (a, b) =>
                        distM(a.value!.location, center) - distM(b.value!.location, center),
                    )
                    .slice(0, 3)
                : all.slice(0, 3);
              return (
                <li className="px-4 py-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium">🏨 숙소 (동선 근처 추천)</span>
                    <a
                      href={searchHref}
                      target="_blank"
                      rel="noreferrer"
                      className="shrink-0 rounded-full bg-black/5 px-2 py-0.5 text-[11px] opacity-70 hover:opacity-100 dark:bg-white/10"
                      title="이 동선 근처·리뷰 좋은 순 숙소 요금 검색"
                    >
                      전체 요금비교 ↗
                    </a>
                  </div>
                  {picks.length > 0 ? (
                    <ul className="mt-2 space-y-1.5">
                      {picks.map((h, hi) => {
                        const hv = h.value!;
                        const nm = displayName(hv) || hv.name;
                        const sname = searchName(hv) || hv.name;
                        return (
                          <li key={hi} className="flex items-center justify-between gap-2 text-sm">
                            <a
                              href={googleMapsPlaceAt(sname, hv.location)}
                              target="_blank"
                              rel="noreferrer"
                              className="min-w-0 truncate hover:underline"
                              title="구글지도에서 위치·리뷰 보기"
                            >
                              📍 {nm}
                              {hv.stars ? ` · ${"★".repeat(hv.stars)}` : ""}
                              {hv.kind === "hostel" ? " · 호스텔" : hv.kind === "guest_house" ? " · 게스트하우스" : ""}
                            </a>
                            <div className="flex shrink-0 items-center gap-2">
                              <a
                                href={naverBlogSearch(`${sname} ${day.city} 후기`)}
                                target="_blank"
                                rel="noreferrer"
                                className="text-xs opacity-60 hover:opacity-100"
                                title="네이버 후기"
                              >
                                📝후기
                              </a>
                              <a
                                href={bookingSearch(`${sname} ${day.city}`, checkin, checkout, adults)}
                                target="_blank"
                                rel="noreferrer"
                                className="text-xs opacity-60 hover:opacity-100"
                                title="이 숙소 요금 검색"
                              >
                                💰요금
                              </a>
                            </div>
                          </li>
                        );
                      })}
                    </ul>
                  ) : (
                    <div className="mt-1 text-xs opacity-60">
                      이 지역 OSM 등록 숙소를 찾지 못했습니다. 위 “전체 요금비교”로 검색하세요.
                    </div>
                  )}
                  <div className="mt-1 text-[11px] opacity-50">
                    실존 숙소(OpenStreetMap)를 동선 근접 순으로 추천합니다. 무료 요금·리뷰 API 가 없어 요금·평점은 지어내지 않으며, 링크에서 확인하세요(§0).
                  </div>
                </li>
              );
            })()}
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

/** 방문지 좌표 평균(동선 중심). 없으면 null. */
function centroid(pts: LatLng[]): LatLng | null {
  if (pts.length === 0) return null;
  const s = pts.reduce((a, p) => ({ lat: a.lat + p.lat, lng: a.lng + p.lng }), { lat: 0, lng: 0 });
  return { lat: s.lat / pts.length, lng: s.lng / pts.length };
}

function addDay(date: string): string {
  return new Date(Date.parse(date) + 86_400_000).toISOString().slice(0, 10);
}

/** 근사 거리(제곱미터 비교용, 정렬 전용이라 하버사인 없이 충분). */
function distM(a: LatLng, b: LatLng): number {
  const dLat = a.lat - b.lat;
  const dLng = (a.lng - b.lng) * Math.cos((a.lat * Math.PI) / 180);
  return dLat * dLat + dLng * dLng;
}

export { DAY_COLORS };
