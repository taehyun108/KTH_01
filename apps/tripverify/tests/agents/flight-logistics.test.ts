import { describe, it, expect } from "vitest";
import { flightAgent } from "@/agents/flight-agent";
import { logisticsAgent } from "@/agents/logistics-agent";
import type { SourceReader } from "@/agents/types";
import type { FlightOption, LogisticsInfo } from "@/core/types/domains";
import type { FlightArgs } from "@/agents/fetchers/flights";
import type { LogisticsArgs } from "@/agents/fetchers/logistics";

const ts = (sec: number) => new Date(Date.parse("2026-08-02T00:00:00Z") + sec * 1000).toISOString();

describe("flight-agent", () => {
  const flight = (price: number, host: string, tier: 1 | 2 | 3, sec: number): FlightOption & { __s: [string, 1 | 2 | 3, number] } => ({
    flight_no: "KE723",
    depart_local: "2026-09-10T09:00:00+09:00",
    arrive_local: "2026-09-10T11:00:00+09:00",
    stops: 0,
    duration_minutes: 120,
    price_estimate_krw: price,
    __s: [host, tier, sec],
  });
  const reader = (f: ReturnType<typeof flight>): SourceReader<FlightArgs, FlightOption> => async () => {
    const { __s, ...value } = f;
    const [host, tier, sec] = __s;
    return [{ value, source: { name: host, url: `https://${host}/`, tier, retrieved_at: ts(sec) }, pass: tier === 1 ? 1 : 2 }];
  };

  it("키 없음(관측 0) → unverified (§0-4)", async () => {
    const facts = await flightAgent(
      { origin: "ICN", destination: "KIX", date: "2026-09-10", adults: 2 },
      [async () => []],
    );
    expect(facts[0]!.value).toBeNull();
    expect(facts[0]!.unverified_reason).toContain("추정하지 않음");
  });

  it("동일 편명 3소스 가격 ±15% + 시간차 → high", async () => {
    const facts = await flightAgent(
      { origin: "ICN", destination: "KIX", date: "2026-09-10", adults: 2 },
      [
        reader(flight(300000, "amadeus.com", 2, 0)),
        reader(flight(310000, "koreanair.com", 1, 30)),
        reader(flight(305000, "skyscanner.net", 2, 90)),
      ],
    );
    expect(facts.length).toBe(1);
    expect(facts[0]!.confidence).toBe("high");
  });
});

describe("logistics-agent", () => {
  const holReader = (host: string, tier: 1 | 2 | 3, dates: string[]): SourceReader<LogisticsArgs, LogisticsInfo> =>
    async () => [{
      value: { public_holidays: dates },
      source: { name: host, url: `https://${host}/`, tier, retrieved_at: ts(0) },
      pass: tier === 1 ? 1 : 2,
    }];

  it("두 공휴일 소스가 동일 목록 → medium", async () => {
    const dates = ["2026-09-21", "2026-09-22", "2026-09-23"];
    const f = await logisticsAgent(
      { country_code: "JP", year: 2026, start_date: "2026-09-10", end_date: "2026-09-25" },
      [holReader("date.nager.at", 2, dates), holReader("openholidaysapi.org", 2, dates)],
    );
    expect(f.confidence).toBe("medium");
    expect(f.value?.public_holidays?.length).toBe(3);
  });

  it("출처 없음 → unverified", async () => {
    const f = await logisticsAgent(
      { country_code: "JP", year: 2026 },
      [async () => { throw new Error("blocked"); }],
    );
    expect(f.value).toBeNull();
  });
});
