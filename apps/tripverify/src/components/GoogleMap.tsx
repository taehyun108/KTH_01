"use client";
import type { Itinerary } from "@/core/types/itinerary";
import type { GeoPoint } from "@/core/types/domains";
import { DAY_COLORS } from "./Timeline";
import { googleMapsEmbed, googleMapsDirections, type LatLng } from "@/lib/format";

/**
 * 지도 뷰 — 구글지도(키 불필요 iframe 임베드) + 일자별 구글지도 길찾기 링크.
 * 하루 동선 전체(모든 경유지)를 구글지도에서 실제 경로로 열 수 있다.
 */
export function GoogleMap({ itinerary }: { itinerary: Itinerary }) {
  const center: LatLng = itinerary.destination_center;
  const mode = itinerary.query.transport[0] ?? "transit";

  return (
    <div className="space-y-3">
      <iframe
        title="Google 지도"
        src={googleMapsEmbed(center, 11)}
        className="h-[380px] w-full rounded-lg border border-black/10 dark:border-white/10"
        style={{ border: 0 }}
        loading="lazy"
        referrerPolicy="no-referrer-when-downgrade"
        allowFullScreen
      />

      <div className="space-y-2">
        <p className="text-xs opacity-60">일자별 동선을 구글지도에서 실제 경로로 열어보세요.</p>
        {itinerary.days.map((day, di) => {
          const stops = day.items
            .map((i) => locOf(i.place.value))
            .filter((l): l is LatLng => l !== null);
          if (stops.length === 0) return null;
          return (
            <a
              key={di}
              href={googleMapsDirections(stops, mode)}
              target="_blank"
              rel="noreferrer"
              className="flex items-center justify-between rounded-lg border border-black/10 px-3 py-2 text-sm hover:bg-black/5 dark:border-white/10 dark:hover:bg-white/5"
            >
              <span className="flex items-center gap-2">
                <span
                  className="inline-block h-3 w-3 rounded-full"
                  style={{ background: DAY_COLORS[di % DAY_COLORS.length] }}
                />
                Day {di + 1} · {day.city} 동선 ({stops.length}곳)
              </span>
              <span className="text-blue-600 dark:text-blue-400">🗺️ 구글지도에서 열기 ↗</span>
            </a>
          );
        })}
      </div>
    </div>
  );
}

function locOf(value: { location?: GeoPoint } | null): LatLng | null {
  return value?.location ? { lat: value.location.lat, lng: value.location.lng } : null;
}
