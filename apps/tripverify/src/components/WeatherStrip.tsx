"use client";
import type { VerifiedFact } from "@/core/types/verified-fact";
import type { WeatherDay } from "@/core/types/domains";
import { ConfidenceBadge } from "./ConfidenceBadge";

/** 날씨 스트립 (§8-5). 일자별 기온·강수확률 + 예보/평년 라벨. */
export function WeatherStrip({
  weather,
  onSelect,
}: {
  weather: VerifiedFact<WeatherDay>[];
  onSelect: (f: VerifiedFact<WeatherDay>, title: string) => void;
}) {
  if (weather.length === 0) return null;
  return (
    <div className="flex gap-2 overflow-x-auto pb-2">
      {weather.map((f, i) => {
        const w = f.value;
        return (
          <button
            key={i}
            onClick={() => onSelect(f, `날씨 ${w?.date ?? ""}`)}
            className="min-w-28 shrink-0 rounded-lg border border-black/10 p-3 text-left text-sm hover:bg-black/5 dark:border-white/10 dark:hover:bg-white/5"
          >
            <div className="flex items-center justify-between">
              <span className="font-medium">{w?.date?.slice(5) ?? "?"}</span>
              <ConfidenceBadge confidence={f.confidence} />
            </div>
            {w ? (
              <>
                <div className="mt-1 text-lg">
                  {Math.round(w.temp_max_c)}° / {Math.round(w.temp_min_c)}°
                </div>
                <div className="text-xs opacity-70">
                  강수 {w.precipitation_probability ?? "-"}%
                  <span className="ml-1">
                    {w.kind === "forecast" ? "예보" : "평년값"}
                  </span>
                </div>
              </>
            ) : (
              <div className="mt-1 text-xs opacity-60">확인 필요</div>
            )}
          </button>
        );
      })}
    </div>
  );
}
