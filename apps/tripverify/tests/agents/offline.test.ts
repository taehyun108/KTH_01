import { describe, it, expect } from "vitest";
import { offlineGeocode, resolveContextOffline } from "@/agents/offline/geocode";
import { dateHolidaysReader } from "@/agents/offline/holidays";
import type { TripQuery } from "@/agents/types";

describe("오프라인 지오코더 (GeoNames 번들, 무료·무네트워크)", () => {
  it("Osaka/JP → 좌표·국가·통화 해석", () => {
    const r = offlineGeocode("Osaka", "JP");
    expect(r).not.toBeNull();
    expect(r!.center.lat).toBeCloseTo(34.69, 1);
    expect(r!.center.lng).toBeCloseTo(135.5, 1);
    expect(r!.country_code).toBe("JP");
    expect(r!.currency_code).toBe("JPY");
  });

  it("국가명(영문)으로 컨텍스트 해석", async () => {
    const q = { country: "Japan" } as TripQuery;
    const ctx = await resolveContextOffline("Kyoto", q);
    expect(ctx.country_code).toBe("JP");
    expect(ctx.currency_code).toBe("JPY");
    expect(ctx.center.lat).toBeCloseTo(35.0, 0);
  });

  it("존재하지 않는 도시 → null / throw", async () => {
    expect(offlineGeocode("존재하지않는도시명xyz")).toBeNull();
    await expect(resolveContextOffline("존재하지않는도시명xyz", {} as TripQuery)).rejects.toThrow();
  });

  it("국내 한글 도시(부산/제주) → KR/KRW 로 해석", () => {
    const busan = offlineGeocode("부산");
    expect(busan?.country_code).toBe("KR");
    expect(busan?.currency_code).toBe("KRW");
    expect(busan?.center.lat).toBeCloseTo(35.1, 0);

    const jeju = offlineGeocode("제주");
    expect(jeju?.country_code).toBe("KR");
    expect(jeju?.center.lat).toBeCloseTo(33.5, 0);
  });
});

describe("date-holidays 오프라인 공휴일 리더", () => {
  it("JP 2026 공휴일을 기간 내로 반환(설날 포함)", async () => {
    const obs = await dateHolidaysReader({
      country_code: "JP",
      year: 2026,
      start_date: "2026-01-01",
      end_date: "2026-12-31",
    });
    expect(obs.length).toBe(1);
    const holidays = obs[0]!.value.public_holidays ?? [];
    expect(holidays).toContain("2026-01-01"); // 元日
    expect(obs[0]!.source.name).toContain("date-holidays");
    expect(obs[0]!.source.tier).toBe(2);
  });

  it("여행 기간으로 필터링된다", async () => {
    const obs = await dateHolidaysReader({
      country_code: "JP",
      year: 2026,
      start_date: "2026-05-01",
      end_date: "2026-05-10",
    });
    const holidays = obs[0]!.value.public_holidays ?? [];
    // 5월 초 골든위크(헌법기념일 05-03 등)만, 1월 설날은 제외
    expect(holidays.every((d) => d >= "2026-05-01" && d <= "2026-05-10")).toBe(true);
    expect(holidays).not.toContain("2026-01-01");
  });
});
