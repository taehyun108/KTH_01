"use client";
import type { Itinerary } from "@/core/types/itinerary";
import { conceptThemes } from "@/agents/poi-select";

/**
 * 여행 컨셉 설명 카드 — 사용자가 입력한 컨셉과, 그에 맞춰 강조된 테마를 보여준다.
 * 일정이 어떤 기준으로 구성됐는지 설명(§ 컨셉 설명 요청).
 */
export function ConceptSummary({ itinerary }: { itinerary: Itinerary }) {
  const { query } = itinerary;
  const themes = conceptThemes(query.concept, query.style);
  const cities = itinerary.cities.map((c) => c.name).join(" · ") || query.destinations.join(" · ");
  const heads = query.party.adults + query.party.children;

  return (
    <div className="rounded-lg border border-blue-200 bg-blue-50/60 p-4 dark:border-blue-900 dark:bg-blue-950/30">
      <h3 className="font-semibold">✨ 이 여행의 컨셉</h3>
      {query.concept ? (
        <p className="mt-1 text-sm italic opacity-90">“{query.concept}”</p>
      ) : (
        <p className="mt-1 text-sm opacity-70">컨셉 미입력 — 유명 명소 위주로 구성했습니다.</p>
      )}
      <div className="mt-2 flex flex-wrap gap-1.5">
        {themes.map((t) => (
          <span key={t} className="rounded-full bg-blue-600/10 px-2 py-0.5 text-xs text-blue-700 dark:bg-blue-400/15 dark:text-blue-300">
            #{t}
          </span>
        ))}
      </div>
      <p className="mt-2 text-xs opacity-70">
        {cities} · {query.start_date}~{query.end_date} · {heads}명 · 예산 약{" "}
        {(query.budget_krw ?? 0).toLocaleString("ko-KR")}원 — 위 테마를 우선해{" "}
        <b>검증된 출처가 있는 유명 장소</b> 위주로, 하루 관광 3곳 이상과 식사를 배치했습니다.
      </p>
      <p className="mt-1 text-xs opacity-70">
        🌆 감수성: <b>전망대·타워는 저녁 야경</b> 시간대에, 시장은 오전에 배치했습니다.
        각 장소의 추천 사유와 식당 대표 메뉴도 함께 표시합니다.
      </p>
    </div>
  );
}
