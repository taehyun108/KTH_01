"use client";
import type { BudgetEstimate } from "@/core/types/itinerary";
import type { VerifiedFact } from "@/core/types/verified-fact";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { krw, localAmount, isoToLocalTime } from "@/lib/format";
import { isRenderable } from "@/core/types/verified-fact";

const CATEGORY_LABEL: Record<string, string> = {
  flight: "✈️ 항공",
  intercity: "🚆 도시간 이동",
  lodging: "🏨 숙박",
  food: "🍽 식사",
  admission: "🎟 입장료",
  local_transport: "🚇 현지 교통",
};

/** 예산 대시보드 (§8-4). 검증(입장료)·추정(가정) 항목을 신뢰도로 구분해 표기. */
export function BudgetBreakdown({
  budget,
  onSelect,
}: {
  budget: BudgetEstimate;
  onSelect: (f: VerifiedFact<unknown>, title: string) => void;
}) {
  const c = budget.currency && isRenderable(budget.currency) ? budget.currency.value : null;

  return (
    <div className="rounded-lg border border-black/10 p-4 dark:border-white/10">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="font-semibold">예산</h3>
        {budget.currency && (
          <button onClick={() => onSelect(budget.currency!, "환율")} className="text-xs underline opacity-70">
            환율 출처
          </button>
        )}
      </div>

      {budget.lines.length === 0 ? (
        <p className="text-sm opacity-60">{budget.note}</p>
      ) : (
        <>
          <table className="w-full text-sm">
            <tbody>
              {budget.lines.map((line, i) => (
                <tr key={i} className="border-b border-black/5 last:border-0 dark:border-white/5">
                  <td className="py-2">{CATEGORY_LABEL[line.category] ?? line.category}</td>
                  <td className="py-2 text-right tabular-nums">
                    {krw(line.amount_krw.value ?? 0)}
                    {c && line.amount_krw.value ? (
                      <span className="ml-1 text-xs opacity-50">
                        ≈ {localAmount((line.amount_krw.value ?? 0) / c.krw_per_unit, c.code)}
                      </span>
                    ) : null}
                  </td>
                  <td className="py-2 pl-2 text-right">
                    <button onClick={() => onSelect(line.amount_krw, line.label)}>
                      {line.amount_krw.confidence === "low" ? (
                        <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-800 dark:bg-amber-900/40 dark:text-amber-300">
                          추정
                        </span>
                      ) : (
                        <ConfidenceBadge confidence={line.amount_krw.confidence} />
                      )}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-black/20 font-semibold dark:border-white/20">
                <td className="py-2">합계(추정 포함)</td>
                <td className="py-2 text-right tabular-nums">{krw(budget.total_krw)}</td>
                <td />
              </tr>
              <tr className="text-xs opacity-70">
                <td className="py-1">· 검증된 항목만</td>
                <td className="py-1 text-right tabular-nums">{krw(budget.verified_krw)}</td>
                <td />
              </tr>
              <tr className="text-xs opacity-70">
                <td className="py-1">· 1인당</td>
                <td className="py-1 text-right tabular-nums">{krw(budget.per_person_krw)}</td>
                <td />
              </tr>
            </tfoot>
          </table>
          {budget.currency && (
            <p className="mt-2 text-xs opacity-50">
              환율 기준: {isoToLocalTime(budget.currency.verification.checked_at)}
            </p>
          )}
          <p className="mt-2 rounded bg-amber-50 p-2 text-xs text-amber-800 dark:bg-amber-950/30 dark:text-amber-300">
            ⚠ {budget.note}
          </p>
        </>
      )}
    </div>
  );
}
