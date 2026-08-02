"use client";
import type { VerifiedFact } from "@/core/types/verified-fact";
import type { CurrencyInfo } from "@/core/types/domains";
import { isRenderable } from "@/core/types/verified-fact";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { krw, localAmount, isoToLocalTime } from "@/lib/format";

/** 예산 대시보드 (§8-4). 현지통화/원화 동시 표기 + 환율 기준시각. */
export function BudgetDashboard({
  currency,
  budgetKrw,
  onSelect,
}: {
  currency: VerifiedFact<CurrencyInfo> | null;
  budgetKrw?: number;
  onSelect: (f: VerifiedFact<CurrencyInfo>, title: string) => void;
}) {
  if (!currency) return null;
  const renderable = isRenderable(currency);
  const c = currency.value;
  return (
    <div className="rounded-lg border border-black/10 p-4 dark:border-white/10">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="font-semibold">예산</h3>
        <button onClick={() => onSelect(currency, "환율")} className="text-xs underline opacity-70">
          출처 보기
        </button>
      </div>
      {renderable && c ? (
        <>
          <div className="flex items-baseline gap-2">
            <span className="text-sm opacity-70">1 {c.code} =</span>
            <span className="text-lg font-semibold">{krw(c.krw_per_unit)}</span>
            <ConfidenceBadge confidence={currency.confidence} />
          </div>
          <div className="mt-1 text-xs opacity-60">
            기준: {isoToLocalTime(currency.verification.checked_at)} · {c.code}/KRW
          </div>
          {budgetKrw && (
            <div className="mt-3 border-t border-black/10 pt-3 text-sm dark:border-white/10">
              <div className="flex justify-between">
                <span>총 예산</span>
                <span className="font-medium">
                  {krw(budgetKrw)} ≈ {localAmount(budgetKrw / c.krw_per_unit, c.code)}
                </span>
              </div>
            </div>
          )}
        </>
      ) : (
        <p className="text-sm text-red-700 dark:text-red-400">
          환율을 교차검증하지 못해 표시하지 않습니다. {currency.unverified_reason ?? ""}
        </p>
      )}
    </div>
  );
}
