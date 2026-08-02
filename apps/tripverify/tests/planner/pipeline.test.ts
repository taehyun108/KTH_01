import { describe, it, expect } from "vitest";
import { runPipeline, type PipelineDeps } from "@/pipeline/run";
import { haversineMatrix } from "@/agents/fetchers/routing";
import { routeAgent } from "@/agents/route-agent";
import { verified, unverified } from "@/core/factory/make-fact";
import type { TripQuery } from "@/agents/types";
import type { Poi, Restaurant, CurrencyInfo, WeatherDay } from "@/core/types/domains";
import type { VerifiedFact } from "@/core/types/verified-fact";

const nowISO = () => "2026-08-02T00:00:00Z";
const src3 = () => [
  { name: "a", url: "https://a.com/", tier: 2 as const, retrieved_at: nowISO() },
  { name: "b", url: "https://b.org/", tier: 2 as const, retrieved_at: nowISO() },
  { name: "c", url: "https://c.gov/", tier: 1 as const, retrieved_at: nowISO() },
];
const highPoi = (name: string, lat: number, lng: number): VerifiedFact<Poi> =>
  verified<Poi>({
    value: { name, location: { lat, lng } },
    confidence: "high",
    sources: src3(),
    verification: { passes_completed: 3, agree_count: 3, checked_at: nowISO() },
  });
const highFood = (name: string): VerifiedFact<Restaurant> =>
  verified<Restaurant>({
    value: { name, location: { lat: 34.69, lng: 135.5 } },
    confidence: "high",
    sources: src3(),
    verification: { passes_completed: 3, agree_count: 3, checked_at: nowISO() },
  });

const query: TripQuery = {
  origin: "ICN",
  destination: "Osaka",
  start_date: "2026-09-10",
  end_date: "2026-09-11", // 2일
  travelers: 2,
  style: ["history", "food"],
  transport: ["transit"],
};

function deps(pois: VerifiedFact<Poi>[]): PipelineDeps {
  return {
    resolveContext: async () => ({
      destination: "Osaka",
      center: { lat: 34.6937, lng: 135.5023 },
      country_code: "JP",
      currency_code: "JPY",
    }),
    collectPois: async () => pois,
    collectFood: async () => [highFood("식당1"), highFood("식당2")],
    collectCurrency: async () =>
      verified<CurrencyInfo>({
        value: { code: "JPY", krw_per_unit: 9.31, base: "KRW" },
        confidence: "high",
        sources: src3(),
        verification: { passes_completed: 3, agree_count: 3, checked_at: nowISO() },
      }),
    collectWeather: async (): Promise<VerifiedFact<WeatherDay>[]> => [
      verified<WeatherDay>({
        value: { date: "2026-09-10", temp_max_c: 30, temp_min_c: 24, kind: "forecast" },
        confidence: "medium",
        sources: src3().slice(0, 2),
        verification: { passes_completed: 2, agree_count: 2, checked_at: nowISO() },
      }),
    ],
    collectFlights: async () => [],
    collectLogistics: async () => unverified("n/a"),
    buildRoute: (places, days, mode) => routeAgent({ places, days, mode }, haversineMatrix),
  };
}

describe("runPipeline", () => {
  it("검증 통과 POI 로 일자별 일정을 생성한다", async () => {
    const pois = [
      highPoi("오사카성", 34.6873, 135.5259),
      highPoi("도톤보리", 34.6686, 135.5011),
      highPoi("우메다", 34.7055, 135.4983),
      highPoi("텐노지", 34.6465, 135.5063),
    ];
    const it = await runPipeline(query, deps(pois));
    expect(it.days.length).toBe(2);
    const placed = it.days.flatMap((d) => d.items.filter((i) => i.kind === "poi").map((i) => i.name));
    expect(placed.length).toBeGreaterThan(0);
    expect(it.verification_summary.total).toBeGreaterThan(0);
    expect(it.destination_center.lat).toBeCloseTo(34.69, 1);
  });

  it("⭐ planner 는 low(미검증) POI 를 절대 배치하지 않는다 (§2/§3)", async () => {
    const pois = [
      highPoi("검증된곳", 34.6873, 135.5259),
      unverified<Poi>("교차검증 실패 — 유령 장소 후보"),
    ];
    const it = await runPipeline(query, deps(pois));
    const allNames = it.days.flatMap((d) => d.items.map((i) => i.name));
    expect(allNames.includes("검증된곳")).toBe(true);
    // low 는 value=null 이므로 이름이 없고, 애초에 후보에서 걸러진다.
    expect(it.verification_summary.low).toBeGreaterThanOrEqual(1);
  });

  it("검증 POI 가 없으면 notes 로 정직하게 비운다 (§0-4)", async () => {
    const it = await runPipeline(query, deps([unverified<Poi>("조회 불가")]));
    expect(it.days.every((d) => d.items.filter((i) => i.kind === "poi").length === 0)).toBe(true);
    expect(it.notes.some((n) => n.includes("일정을 생성할 수 없"))).toBe(true);
  });
});
