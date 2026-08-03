"use client";
import type { Itinerary } from "@/core/types/itinerary";
import type { VerifiedFact } from "@/core/types/verified-fact";

/** 검증 리포트 (§8-6). high/medium/low 비율 + 검증 실패 항목 목록. */
export function VerificationReport({
  itinerary,
  onSelect,
}: {
  itinerary: Itinerary;
  onSelect: (f: VerifiedFact<unknown>, title: string) => void;
}) {
  const s = itinerary.verification_summary;
  const pct = (n: number) => (s.total > 0 ? Math.round((n / s.total) * 100) : 0);

  const failed: { title: string; fact: VerifiedFact<unknown> }[] = [];
  for (const d of itinerary.days) {
    for (const it of d.items) {
      if (it.place.confidence === "low") failed.push({ title: it.name, fact: it.place });
    }
  }
  if (itinerary.currency?.confidence === "low")
    failed.push({ title: "환율", fact: itinerary.currency });
  for (const w of itinerary.weather)
    if (w.confidence === "low") failed.push({ title: `날씨 ${w.value?.date ?? ""}`, fact: w });

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-black/10 p-4 dark:border-white/10">
        <h3 className="mb-3 font-semibold">검증 등급 분포</h3>
        <div className="flex h-4 w-full overflow-hidden rounded-full bg-black/10 dark:bg-white/10">
          <div className="bg-green-500" style={{ width: `${pct(s.high)}%` }} />
          <div className="bg-amber-500" style={{ width: `${pct(s.medium)}%` }} />
          <div className="bg-red-500" style={{ width: `${pct(s.low)}%` }} />
        </div>
        <div className="mt-2 flex gap-4 text-sm">
          <span>🟢 검증됨 {s.high} ({pct(s.high)}%)</span>
          <span>🟡 부분 {s.medium} ({pct(s.medium)}%)</span>
          <span>🔴 확인필요 {s.low} ({pct(s.low)}%)</span>
        </div>
        <p className="mt-2 text-xs opacity-60">
          총 {s.total}개 FACT · high 비율 {Math.round(s.high_ratio * 100)}% (목표 80%)
        </p>
      </div>

      {failed.length > 0 && (
        <div className="rounded-lg border border-red-200 p-4 dark:border-red-900">
          <h3 className="mb-2 font-semibold text-red-700 dark:text-red-400">
            저신뢰(단일 출처) 항목 {failed.length}건 — 🔴 배지와 함께 표시됨
          </h3>
          <ul className="space-y-1 text-sm">
            {failed.map((f, i) => (
              <li key={i}>
                <button onClick={() => onSelect(f.fact, f.title)} className="underline">
                  {f.title}
                </button>
                <span className="opacity-60"> — {f.fact.unverified_reason ?? "교차검증 미달"}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {itinerary.notes.length > 0 && (
        <ul className="rounded-lg bg-black/5 p-4 text-sm dark:bg-white/5">
          {itinerary.notes.map((n, i) => (
            <li key={i}>• {n}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
