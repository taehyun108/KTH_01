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

/** 최소비용(budget) 등급 가정 — 예산 초과 시 사용. */
export const BUDGET_ASSUMPTIONS_MIN = {
  lodging_per_night_per_person_krw: 40_000, // 게스트하우스/저가 숙소
  food_meal_multiplier: 0.6, // 가성비 식사
  local_transport_per_day_per_person_krw: 8_000,
} as const;

export type BudgetTier = "standard" | "budget";

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
  budget_krw?: number;
  /** 비용 등급. budget=최소비용(예산 초과 시). */
  tier?: BudgetTier;
  /** 국내여행(원화 기준, 환전 불필요). */
  domestic?: boolean;
  checkedAt?: string;
}

/**
 * 예산 추정 (§8-4 확장). tier=budget 이면 최소비용 가정으로 재구성.
 * 국내여행(domestic)이면 원화 기준(환율 1)으로 입장료를 계산한다.
 */
export function estimateBudget(input: BudgetInput): BudgetEstimate {
  const checkedAt = input.checkedAt ?? new Date().toISOString();
  const heads = totalTravelers(input.party);
  const fx = input.currency && isRenderable(input.currency) ? input.currency : null;
  const tier: BudgetTier = input.tier ?? "standard";
  const domestic = input.domestic ?? false;
  const lines: BudgetLine[] = [];

  const lodgingPerNight =
    tier === "budget"
      ? BUDGET_ASSUMPTIONS_MIN.lodging_per_night_per_person_krw
      : BUDGET_ASSUMPTIONS.lodging_per_night_per_person_krw;
  const foodMult = tier === "budget" ? BUDGET_ASSUMPTIONS_MIN.food_meal_multiplier : 1;
  const localPerDay =
    tier === "budget"
      ? BUDGET_ASSUMPTIONS_MIN.local_transport_per_day_per_person_krw
      : BUDGET_ASSUMPTIONS.local_transport_per_day_per_person_krw;

  const push = (category: BudgetCategory, label: string, amount_krw: VerifiedFact<number>) =>
    lines.push({ category, label, amount_krw });

  // 1) 항공 — 검증값 있으면 사용
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

  // 2) 도시 간 이동
  if (input.transfers.length > 0) {
    let intercity = 0;
    for (const t of input.transfers) {
      const per = BUDGET_ASSUMPTIONS.intercity_per_km_krw[t.suggested_mode] ?? 150;
      const base = t.suggested_mode === "flight" ? BUDGET_ASSUMPTIONS.flight_base_krw : 0;
      intercity += (base + t.distance_km * per) * heads;
    }
    push("intercity", "도시 간 이동", estimateMoney(intercity, "거리×모드 단가 가정", checkedAt));
  }

  // 3) 숙박
  const lodging = lodgingPerNight * input.nights * heads;
  push("lodging", `숙박(${input.nights}박${tier === "budget" ? "·최소비용" : ""})`, estimateMoney(lodging, `1인1박 ${Math.round(lodgingPerNight / 1000)}천원 가정`, checkedAt));

  // 4) 식사
  const perMeal = averageMealKrw(input.food) * foodMult;
  const food = perMeal * BUDGET_ASSUMPTIONS.meals_per_day * input.days * heads;
  push("food", `식사(${input.days}일×3식${tier === "budget" ? "·가성비" : ""})`, estimateMoney(food, "가격대 평균 기반 추정", checkedAt));

  // 5) 입장료 — 조회된 POI 요금 합계(국내=원화, 해외=검증 환율)
  const rate = domestic ? 1 : fx ? fx.value.krw_per_unit : null;
  if (rate !== null) {
    const feeLocal = input.pois.reduce((sum, p) => {
      const fee = hasSourcedValue(p) ? p.value.admission_fee_local : null;
      return sum + (typeof fee === "number" ? fee : 0);
    }, 0);
    if (feeLocal > 0) {
      const admissionKrw = feeLocal * rate * heads;
      const fact =
        fx && !domestic
          ? verifiedMoney(admissionKrw, fx, checkedAt)
          : estimateMoney(admissionKrw, "입장료 합계(원화 기준)", checkedAt);
      push("admission", "입장료(조회된 요금 합계)", fact);
    }
  }

  // 6) 현지 교통
  const localTransport = localPerDay * input.days * heads;
  push("local_transport", "현지 교통", estimateMoney(localTransport, `1인1일 ${Math.round(localPerDay / 1000)}천원 가정`, checkedAt));

  const total_krw = lines.reduce((s, l) => s + (l.amount_krw.value ?? 0), 0);
  const verified_krw = lines
    .filter((l) => l.amount_krw.confidence !== "low")
    .reduce((s, l) => s + (l.amount_krw.value ?? 0), 0);

  const budget_krw = input.budget_krw;
  const over_budget = budget_krw !== undefined && total_krw > budget_krw;
  const shortfall_krw = over_budget ? total_krw - budget_krw! : 0;

  const noteBase = domestic
    ? "국내여행(원화 기준). 숙박·식사·교통은 계획용 추정이며 실제 요금은 검색 링크에서 확인하세요."
    : "숙박·식사·교통·도시간 이동은 계획용 '추정(가정)'입니다. 실제 요금은 검색 링크에서 확인하세요.";
  const noteTier = tier === "budget" ? " 예산에 맞춰 최소비용으로 재구성했습니다." : "";

  return {
    currency: input.currency,
    lines,
    total_krw,
    verified_krw,
    per_person_krw: heads > 0 ? Math.round(total_krw / heads) : total_krw,
    note: noteBase + noteTier,
    ...(budget_krw !== undefined ? { budget_krw } : {}),
    tier,
    over_budget,
    shortfall_krw,
    domestic,
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
