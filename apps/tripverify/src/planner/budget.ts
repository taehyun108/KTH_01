import type { VerifiedFact, Source } from "@/core/types/verified-fact";
import type { Poi, Restaurant, CurrencyInfo, FlightOption } from "@/core/types/domains";
import type {
  BudgetEstimate,
  BudgetLine,
  BudgetCategory,
  CityTransfer,
} from "@/core/types/itinerary";
import type { TravelParty } from "@/agents/types";
import { totalTravelers } from "@/agents/types";
import { verified } from "@/core/factory/make-fact";
import { isRenderable, hasSourcedValue } from "@/core/types/verified-fact";

/**
 * 계획용 가정치(§0 정직성: '사실'이 아니라 '가정'임을 low + 추정 출처로 명시).
 * 실제 예약가가 아니므로 절대 high/medium 으로 올리지 않는다.
 */
export const BUDGET_ASSUMPTIONS = {
  lodging_per_night_per_person_krw: 90_000, // 3성급 기준 가정
  food_per_meal_by_level_krw: { 1: 8_000, 2: 15_000, 3: 30_000, 4: 60_000 } as Record<number, number>,
  food_default_meal_krw: 15_000,
  meals_per_day: 3,
  local_transport_per_day_per_person_krw: 12_000,
  intercity_per_km_krw: { train: 200, car: 150, flight: 60 } as Record<string, number>,
  flight_base_krw: 120_000,
} as const;

function estimateSource(checkedAt: string, method: string): Source {
  return {
    name: "TripVerify 추정(계획용 가정)",
    url: "https://tripverify.local/estimate",
    tier: 3,
    retrieved_at: checkedAt,
    excerpt: method.slice(0, 30),
  };
}

/** 추정 금액 FACT (항상 low). */
function estimateMoney(amount: number, method: string, checkedAt: string): VerifiedFact<number> {
  return verified<number>({
    value: Math.round(amount),
    confidence: "low",
    sources: [estimateSource(checkedAt, method)],
    verification: { passes_completed: 1, agree_count: 0, checked_at: checkedAt },
  });
}

/** 검증 금액 FACT (입장료 합계 등, FX 신뢰도 승계, 최대 medium). */
function verifiedMoney(
  amount: number,
  fx: VerifiedFact<CurrencyInfo>,
  checkedAt: string,
): VerifiedFact<number> {
  const confidence = fx.confidence === "high" ? "medium" : fx.confidence; // 파생합이므로 상한 medium
  if (confidence === "low" || fx.sources.length < 2) {
    return estimateMoney(amount, "입장료 합계(환율 미검증)", checkedAt);
  }
  return verified<number>({
    value: Math.round(amount),
    confidence,
    sources: fx.sources,
    verification: {
      passes_completed: fx.verification.passes_completed,
      agree_count: fx.verification.agree_count,
      checked_at: checkedAt,
    },
  });
}

export interface BudgetInput {
  currency: VerifiedFact<CurrencyInfo> | null;
  pois: VerifiedFact<Poi>[]; // 검증 통과 POI
  food: VerifiedFact<Restaurant>[]; // 검증 통과 식당
  transfers: CityTransfer[];
  flights: VerifiedFact<FlightOption>[];
  days: number;
  nights: number;
  party: TravelParty;
  checkedAt?: string;
}

/**
 * 예산 추정 (§8-4 확장). 카테고리별로 KRW 금액을 산출하되,
 * 실제 조회된 입장료+검증 환율로 계산한 '입장료'만 검증(medium), 나머지는 추정(low).
 */
export function estimateBudget(input: BudgetInput): BudgetEstimate {
  const checkedAt = input.checkedAt ?? new Date().toISOString();
  const heads = totalTravelers(input.party);
  const fx = input.currency && isRenderable(input.currency) ? input.currency : null;
  const lines: BudgetLine[] = [];

  const push = (category: BudgetCategory, label: string, amount_krw: VerifiedFact<number>) =>
    lines.push({ category, label, amount_krw });

  // 1) 항공 — 검증값 있으면 사용, 없으면 라인 생략(추정 남발 금지)
  const flightPrice = input.flights.find((f) => isRenderable(f) && f.value.price_estimate_krw);
  if (flightPrice && isRenderable(flightPrice) && flightPrice.value.price_estimate_krw) {
    const total = flightPrice.value.price_estimate_krw * heads;
    push("flight", "항공(왕복 추정 합계)", verified<number>({
      value: total,
      confidence: flightPrice.confidence,
      sources: flightPrice.sources,
      verification: { ...flightPrice.verification, checked_at: checkedAt },
    }));
  }

  // 2) 도시 간 이동 — 거리×모드 단가(추정)
  if (input.transfers.length > 0) {
    let intercity = 0;
    for (const t of input.transfers) {
      const per = BUDGET_ASSUMPTIONS.intercity_per_km_krw[t.suggested_mode] ?? 150;
      const base = t.suggested_mode === "flight" ? BUDGET_ASSUMPTIONS.flight_base_krw : 0;
      intercity += (base + t.distance_km * per) * heads;
    }
    push("intercity", "도시 간 이동", estimateMoney(intercity, "거리×모드 단가 가정", checkedAt));
  }

  // 3) 숙박 — 1인 1박 가정
  const lodging = BUDGET_ASSUMPTIONS.lodging_per_night_per_person_krw * input.nights * heads;
  push("lodging", `숙박(${input.nights}박)`, estimateMoney(lodging, "1인1박 9만원 가정", checkedAt));

  // 4) 식사 — 검증 식당의 가격대 평균으로 1식 단가 추정
  const perMeal = averageMealKrw(input.food);
  const food = perMeal * BUDGET_ASSUMPTIONS.meals_per_day * input.days * heads;
  push("food", `식사(${input.days}일×3식)`, estimateMoney(food, "가격대 평균 기반 추정", checkedAt));

  // 5) 입장료 — 검증된 POI 실제 요금 × 검증 환율 (유일한 검증 라인)
  if (fx) {
    const feeLocal = input.pois.reduce((sum, p) => {
      const fee = hasSourcedValue(p) ? p.value.admission_fee_local : null;
      return sum + (typeof fee === "number" ? fee : 0);
    }, 0);
    if (feeLocal > 0) {
      const admissionKrw = feeLocal * fx.value.krw_per_unit * heads;
      push("admission", "입장료(검증된 요금 합계)", verifiedMoney(admissionKrw, fx, checkedAt));
    }
  }

  // 6) 현지 교통 — 1인 1일 가정
  const localTransport = BUDGET_ASSUMPTIONS.local_transport_per_day_per_person_krw * input.days * heads;
  push("local_transport", "현지 교통", estimateMoney(localTransport, "1인1일 1.2만원 가정", checkedAt));

  const total_krw = lines.reduce((s, l) => s + (l.amount_krw.value ?? 0), 0);
  const verified_krw = lines
    .filter((l) => l.amount_krw.confidence !== "low")
    .reduce((s, l) => s + (l.amount_krw.value ?? 0), 0);

  return {
    currency: input.currency,
    lines,
    total_krw,
    verified_krw,
    per_person_krw: heads > 0 ? Math.round(total_krw / heads) : total_krw,
    note:
      "숙박·식사·교통·도시간 이동은 계획용 '추정(가정)'이며 실제 예약가가 아닙니다. " +
      "입장료만 검증된 요금과 검증 환율로 계산했습니다.",
  };
}

function averageMealKrw(food: VerifiedFact<Restaurant>[]): number {
  const levels = food
    .filter(hasSourcedValue)
    .map((f) => f.value.price_level)
    .filter((l): l is 1 | 2 | 3 | 4 => l !== undefined);
  if (levels.length === 0) return BUDGET_ASSUMPTIONS.food_default_meal_krw;
  const avg =
    levels.reduce((s, l) => s + (BUDGET_ASSUMPTIONS.food_per_meal_by_level_krw[l] ?? 15_000), 0) /
    levels.length;
  return avg;
}
