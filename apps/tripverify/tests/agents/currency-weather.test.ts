import { describe, it, expect } from "vitest";
import { currencyAgent } from "@/agents/currency-agent";
import { weatherAgent } from "@/agents/weather-agent";
import type { SourceReader } from "@/agents/types";
import type { CurrencyInfo, WeatherDay } from "@/core/types/domains";
import type { CurrencyArgs } from "@/agents/fetchers/currency";
import type { WeatherArgs } from "@/agents/fetchers/weather";
import { isRenderable } from "@/core/types/verified-fact";

/**
 * 주의: 아래 리더는 검증 '로직'을 결정론적으로 시험하기 위한 테스트 더블(합성)이다.
 * 실제 앱은 실 HTTP 소스만 사용하며, 이 합성 데이터는 UI 로 전달되지 않는다(§0).
 */
const T0 = Date.parse("2026-08-02T00:00:00Z");
const ts = (sec: number) => new Date(T0 + sec * 1000).toISOString();

const fxReader = (
  rate: number,
  host: string,
  tier: 1 | 2 | 3,
  sec: number,
): SourceReader<CurrencyArgs, CurrencyInfo> => async ({ code }) => [
  {
    value: { code, krw_per_unit: rate, base: "KRW" },
    source: { name: host, url: `https://${host}/`, tier, retrieved_at: ts(sec) },
    pass: tier === 1 ? 1 : 2,
  },
];

describe("currency-agent", () => {
  it("독립 3소스 동의 + 60s 시간차 → high", async () => {
    const f = await currencyAgent({ code: "JPY" }, [
      fxReader(9.31, "frankfurter.dev", 1, 0),
      fxReader(9.315, "exchangerate.host", 2, 30),
      fxReader(9.312, "open.er-api.com", 2, 90),
    ]);
    expect(f.confidence).toBe("high");
    expect(f.value?.code).toBe("JPY");
    expect(isRenderable(f)).toBe(true);
  });

  it("모든 소스 실패 → unverified (§0-4)", async () => {
    const failing: SourceReader<CurrencyArgs, CurrencyInfo> = async () => {
      throw new Error("blocked");
    };
    const f = await currencyAgent({ code: "JPY" }, [failing, failing]);
    expect(f.value).toBeNull();
    expect(f.confidence).toBe("low");
    expect(f.unverified_reason).toBeDefined();
  });

  it("한 소스만 살아있으면 low (교차검증 불가)", async () => {
    const f = await currencyAgent({ code: "JPY" }, [
      fxReader(9.31, "frankfurter.dev", 1, 0),
    ]);
    expect(f.confidence).toBe("low");
  });
});

const wReader = (
  host: string,
  tier: 1 | 2 | 3,
  temps: { date: string; max: number; min: number }[],
  sec: number,
): SourceReader<WeatherArgs, WeatherDay> => async () =>
  temps.map((t) => ({
    value: { date: t.date, temp_max_c: t.max, temp_min_c: t.min, kind: "forecast" as const },
    source: { name: host, url: `https://${host}/`, tier, retrieved_at: ts(sec) },
    pass: tier === 1 ? (1 as const) : (2 as const),
  }));

describe("weather-agent", () => {
  const days = [
    { date: "2026-09-10", max: 30, min: 24 },
    { date: "2026-09-11", max: 31, min: 25 },
  ];
  const daysClose = [
    { date: "2026-09-10", max: 31, min: 23 }, // ±3°C 이내
    { date: "2026-09-11", max: 29, min: 26 },
  ];

  it("2독립 소스가 근접 → 날짜별 medium", async () => {
    const facts = await weatherAgent(
      { center: { lat: 34.69, lng: 135.5 }, start_date: "2026-09-10", end_date: "2026-09-11" },
      [wReader("met.no", 1, days, 0), wReader("open-meteo.com", 2, daysClose, 10)],
    );
    expect(facts.length).toBe(2);
    expect(facts.every((f) => f.confidence === "medium")).toBe(true);
    expect(facts[0]!.value?.date).toBe("2026-09-10");
  });

  it("단일 소스 → low", async () => {
    const facts = await weatherAgent(
      { center: { lat: 34.69, lng: 135.5 }, start_date: "2026-09-10", end_date: "2026-09-11" },
      [wReader("open-meteo.com", 2, days, 0)],
    );
    expect(facts.every((f) => f.confidence === "low")).toBe(true);
  });
});
