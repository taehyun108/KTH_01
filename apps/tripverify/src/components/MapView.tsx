"use client";
import { useEffect, useRef } from "react";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Itinerary } from "@/core/types/itinerary";
import { DAY_COLORS } from "./Timeline";

/**
 * 지도 뷰 (§8-3). 일자별 색상 구분 동선. MapLibre GL + OSM(키 불필요).
 * 좌표는 검증된 POI 의 것만 사용한다.
 */
export function MapView({ itinerary }: { itinerary: Itinerary }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    const map = new maplibregl.Map({
      container: ref.current,
      style: "https://demotiles.maplibre.org/style.json",
      center: [itinerary.destination_center.lng, itinerary.destination_center.lat],
      zoom: 11,
    });

    map.on("load", () => {
      itinerary.days.forEach((day, di) => {
        const color = DAY_COLORS[di % DAY_COLORS.length]!;
        const coords: [number, number][] = [];
        day.items.forEach((item) => {
          const v = item.place.value as { location?: { lat: number; lng: number } } | null;
          if (!v?.location) return;
          const lngLat: [number, number] = [v.location.lng, v.location.lat];
          coords.push(lngLat);
          new maplibregl.Marker({ color })
            .setLngLat(lngLat)
            .setPopup(new maplibregl.Popup().setText(`${item.start} ${item.name}`))
            .addTo(map);
        });
        if (coords.length >= 2) {
          map.addSource(`route-${di}`, {
            type: "geojson",
            data: {
              type: "Feature",
              properties: {},
              geometry: { type: "LineString", coordinates: coords },
            },
          });
          map.addLayer({
            id: `route-${di}`,
            type: "line",
            source: `route-${di}`,
            paint: { "line-color": color, "line-width": 3 },
          });
        }
      });
    });

    return () => map.remove();
  }, [itinerary]);

  return <div ref={ref} className="h-[420px] w-full rounded-lg border border-black/10 dark:border-white/10" />;
}
