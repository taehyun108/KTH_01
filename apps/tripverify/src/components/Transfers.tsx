"use client";
import type { CityTransfer } from "@/core/types/itinerary";
import type { VerifiedFact } from "@/core/types/verified-fact";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { minutesLabel, num } from "@/lib/format";

const MODE_LABEL: Record<string, string> = { train: "🚄 기차", car: "🚗 자동차", flight: "✈️ 항공" };

/** 도시 간 이동방법. 좌표 기반 추정이므로 신뢰도 배지로 명시(§0). */
export function Transfers({
  transfers,
  onSelect,
}: {
  transfers: CityTransfer[];
  onSelect: (f: VerifiedFact<unknown>, title: string) => void;
}) {
  if (transfers.length === 0) return null;
  return (
    <div className="rounded-lg border border-black/10 p-4 dark:border-white/10">
      <h3 className="mb-3 font-semibold">도시 간 이동</h3>
      <ul className="space-y-2">
        {transfers.map((t, i) => (
          <li key={i} className="flex items-center justify-between gap-3 text-sm">
            <span className="font-medium">
              {t.from_city} → {t.to_city}
            </span>
            <button
              onClick={() => onSelect(t.fact, `${t.from_city}→${t.to_city} 이동`)}
              className="flex items-center gap-2 text-right"
            >
              <span>
                {MODE_LABEL[t.suggested_mode] ?? t.suggested_mode} · {num(t.distance_km)}km ·{" "}
                {minutesLabel(t.fact.value?.duration_minutes ?? 0)}
              </span>
              <ConfidenceBadge confidence={t.fact.confidence} />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
