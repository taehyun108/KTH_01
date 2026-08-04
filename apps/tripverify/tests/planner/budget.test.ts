import { describe, it, expect } from "vitest";
import { estimateBudget } from "@/planner/budget";
import { planTransfers } from "@/agents/transfer-agent";
import { verified } from "@/core/factory/make-fact";
import type { CurrencyInfo, Poi, Restaurant } from "@/core/types/domains";
import type { VerifiedFact } from "@/core/types/verified-fact";

const nowISO = () => "2026-08-02T00:00:00Z";
const src3 = () => [
  { name: "a", url: "https://a.com/", tier: 2 as const, retrieved_at: nowISO() },
  { name: "b", url: "https://b.org/", tier: 2 as const, retrieved_at: nowISO() },
  { name: "c", url: "https://c.gov/", tier: 1 as const, retrieved_at: nowISO() },
];
const fx = (): VerifiedFact<CurrencyInfo> =>
  verified<CurrencyInfo>({
    value: { code: "JPY", krw_per_unit: 9.31, base: "KRW" },
    confidence: "high",
    sources: src3(),
    verification: { passes_completed: 3, agree_count: 3, checked_at: nowISO() },
  });
const poiWithFee = (fee: number): VerifiedFact<Poi> =>
  verified<Poi>({
    value: { name: "성", location: { lat: 34.6, lng: 135.5 }, admission_fee_local: fee },
    confidence: "high",
    sources: src3(),
    verification: { passes_completed: 3, agree_count: 3, checked_at: nowISO() },
  });

describe("estimateBudget", () => {
  const base = {
    pois: [poiWithFee(600), poiWithFee(1000)], // 1600엔
    food: [] as VerifiedFact<Restaurant>[],
    transfers: [],
    flights: [],
    days: 4,
    nights: 3,
    party: { adults: 2, children: 0 },
    checkedAt: nowISO(),
  };

  it("입장료는 검증(medium), 숙박/식사/교통은 추정(low)", () => {
    const b = estimateBudget({ currency: fx(), ...base });
    const admission = b.lines.find((l) => l.category === "admission");
    const lodging = b.lines.find((l) => l.category === "lodging");
    expect(admission?.amount_krw.confidence).toBe("medium");
    // 1600엔 × 9.31 × 2인 ≈ 29,792원
    expect(admission?.amount_krw.value).toBe(Math.round(1600 * 9.31 * 2));
    expect(lodging?.amount_krw.confidence).toBe("low");
  });

  it("total >= verified, per_person = total/인원", () => {
    const b = estimateBudget({ currency: fx(), ...base });
    expect(b.total_krw).toBeGreaterThanOrEqual(b.verified_krw);
    expect(b.per_person_krw).toBe(Math.round(b.total_krw / 2));
    expect(b.verified_krw).toBeGreaterThan(0); // 입장료 검증분 존재
  });

  it("환율 미검증이면 입장료 라인 없음(추정 남발 금지)", () => {
    const b = estimateBudget({ currency: null, ...base });
    expect(b.lines.find((l) => l.category === "admission")).toBeUndefined();
    expect(b.verified_krw).toBe(0); // 검증 항목 없음
  });

  it("예산 초과 감지 + 최소비용(budget) 등급은 더 저렴", () => {
    const std = estimateBudget({ currency: fx(), ...base, budget_krw: 100_000 });
    expect(std.over_budget).toBe(true);
    expect(std.shortfall_krw).toBeGreaterThan(0);

    const cheap = estimateBudget({ currency: fx(), ...base, tier: "budget", budget_krw: 100_000 });
    expect(cheap.total_krw).toBeLessThan(std.total_krw); // 최소비용이 더 쌈
    expect(cheap.tier).toBe("budget");
  });

  it("충분한 예산이면 over_budget=false", () => {
    const b = estimateBudget({ currency: fx(), ...base, budget_krw: 100_000_000 });
    expect(b.over_budget).toBe(false);
    expect(b.shortfall_krw).toBe(0);
  });

  it("국내여행(domestic): 환율 없이 원화 기준으로 입장료 계산", () => {
    const b = estimateBudget({ currency: null, ...base, domestic: true });
    const admission = b.lines.find((l) => l.category === "admission");
    expect(admission).toBeDefined(); // 원화 기준으로 계산됨
    expect(admission?.amount_krw.value).toBe(Math.round(1600 * 1 * 2)); // rate=1
    expect(b.domestic).toBe(true);
    expect(b.note).toContain("국내여행");
  });
});

describe("planTransfers (도시 간 이동)", () => {
  it("가까운 두 도시 → car, 소요시간/거리 산출", () => {
    const t = planTransfers([
      { name: "오사카", center: { lat: 34.69, lng: 135.5 } },
      { name: "교토", center: { lat: 35.01, lng: 135.77 } }, // ~43km
    ]);
    expect(t.length).toBe(1);
    expect(t[0]!.suggested_mode).toBe("car");
    expect(t[0]!.distance_km).toBeGreaterThan(30);
    expect(t[0]!.fact.confidence).toBe("low"); // 추정
  });

  it("먼 두 도시 → flight", () => {
    const t = planTransfers([
      { name: "서울", center: { lat: 37.56, lng: 126.97 } },
      { name: "오사카", center: { lat: 34.69, lng: 135.5 } }, // ~900km
    ]);
    expect(t[0]!.suggested_mode).toBe("flight");
  });
});
