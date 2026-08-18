import { describe, it, expect } from "vitest";
import { assembleDay, fitsOpeningHours, summarize, PLAN } from "@/planner/assemble";
import { verified, unverified } from "@/core/factory/make-fact";
import type { Poi, Restaurant } from "@/core/types/domains";
import type { VerifiedFact } from "@/core/types/verified-fact";

const nowISO = () => "2026-08-02T00:00:00Z";
const twoSources = () => [
  { name: "a", url: "https://a.com/", tier: 2 as const, retrieved_at: nowISO() },
  { name: "b", url: "https://b.org/", tier: 2 as const, retrieved_at: nowISO() },
];
function poiFact(poi: Poi): VerifiedFact<Poi> {
  return verified<Poi>({
    value: poi,
    confidence: "medium",
    sources: twoSources(),
    verification: { passes_completed: 2, agree_count: 2, checked_at: nowISO() },
  });
}
function foodFact(r: Restaurant): VerifiedFact<Restaurant> {
  return verified<Restaurant>({
    value: r,
    confidence: "medium",
    sources: twoSources(),
    verification: { passes_completed: 2, agree_count: 2, checked_at: nowISO() },
  });
}
const loc = { lat: 34.69, lng: 135.5 };

describe("fitsOpeningHours", () => {
  it("휴무일(closed_days)이면 false", () => {
    const poi: Poi = { name: "x", location: loc, closed_days: [1] };
    expect(fitsOpeningHours(poi, 1, 600, 690)).toBe(false);
    expect(fitsOpeningHours(poi, 2, 600, 690)).toBe(true);
  });
  it("주간 배열의 해당 요일이 null 이면 휴무", () => {
    const poi: Poi = {
      name: "x",
      location: loc,
      opening_hours: [null, "09:00-17:00", "09:00-17:00", "09:00-17:00", "09:00-17:00", "09:00-17:00", null],
    };
    expect(fitsOpeningHours(poi, 0, 600, 690)).toBe(false); // 일요일 휴무
    expect(fitsOpeningHours(poi, 1, 600, 690)).toBe(true);
  });
  it("영업시간 창 밖이면 false", () => {
    const poi: Poi = { name: "x", location: loc, opening_hours: Array(7).fill("13:00-17:00") };
    expect(fitsOpeningHours(poi, 3, 9 * 60, 9 * 60 + 90)).toBe(false); // 오전
    expect(fitsOpeningHours(poi, 3, 13 * 60, 14 * 60)).toBe(true);
  });
  it("시간 정보 없으면 배치 허용(추정 금지)", () => {
    expect(fitsOpeningHours({ name: "x", location: loc }, 3, 600, 690)).toBe(true);
  });
});

describe("assembleDay 제약 (§6, §10)", () => {
  it("휴무일 POI 는 배치되지 않고 경고로 남는다", () => {
    const day = assembleDay({
      date: "2026-09-13", // 일요일
      weekday: 0,
      city: "테스트",
      pois: [poiFact({ name: "월요일만휴무아님", location: loc, closed_days: [0] })],
      legMinutes: [0],
      legMode: "walk",
      legEstimated: true,
      legSource: "est",
    });
    expect(day.items.some((i) => i.name === "월요일만휴무아님")).toBe(false);
    expect(day.warnings.some((w) => w.includes("휴무"))).toBe(true);
  });

  it("하루 활동 10시간 상한 초과 시 이후 제외 + 경고", () => {
    const many = Array.from({ length: 12 }, (_, i) =>
      poiFact({ name: `P${i}`, location: loc }),
    );
    const day = assembleDay({
      date: "2026-09-14",
      weekday: 1,
      city: "테스트",
      pois: many,
      legMinutes: many.map(() => 0),
      legMode: "walk",
      legEstimated: true,
      legSource: "est",
    });
    expect(day.total_activity_minutes).toBeLessThanOrEqual(PLAN.MAX_ACTIVITY_MIN);
    expect(day.warnings.some((w) => w.includes("10시간"))).toBe(true);
  });

  it("출처가 전혀 없는(null) 미확인 POI 는 배치되지 않는다", () => {
    const low = unverified<Poi>("확인 필요");
    const day = assembleDay({
      date: "2026-09-14",
      weekday: 1,
      city: "테스트",
      pois: [low],
      legMinutes: [0],
      legMode: "walk",
      legEstimated: true,
      legSource: "est",
    });
    expect(day.items.length).toBe(0);
  });

  it("단일 출처(low)라도 실존 장소는 배지를 달아 배치된다", () => {
    const lowPoi = verified<Poi>({
      value: { name: "OSM단일출처장소", location: loc },
      confidence: "low",
      sources: [{ name: "OSM", url: "https://overpass-api.de/", tier: 2, retrieved_at: nowISO() }],
      verification: { passes_completed: 1, agree_count: 1, checked_at: nowISO() },
    });
    const day = assembleDay({
      date: "2026-09-14",
      weekday: 1,
      city: "테스트",
      pois: [lowPoi],
      legMinutes: [0],
      legMode: "walk",
      legEstimated: true,
      legSource: "est",
    });
    const item = day.items.find((i) => i.name === "OSM단일출처장소");
    expect(item).toBeDefined();
    expect(item!.place.confidence).toBe("low"); // 정직한 배지 유지
  });

  it("식당(점심/저녁)이 삽입된다", () => {
    const day = assembleDay({
      date: "2026-09-14",
      weekday: 1,
      city: "테스트",
      pois: [poiFact({ name: "A", location: loc }), poiFact({ name: "B", location: loc })],
      legMinutes: [0, 120], // B 진입 전 2시간 → 점심시간대 진입
      legMode: "transit",
      legEstimated: true,
      legSource: "est",
      lunch: foodFact({ name: "점심집", location: loc }),
      dinner: foodFact({ name: "저녁집", location: loc }),
    });
    expect(day.items.some((i) => i.kind === "food" && i.name === "점심집")).toBe(true);
    expect(day.items.some((i) => i.kind === "food" && i.name === "저녁집")).toBe(true);
  });

  it("점심이 POI 와 시간이 겹치지 않는다(오전에 POI 가 몰린 경우)", () => {
    // 스크린샷 재현: 3개 POI 가 12:16 직전까지 이어져 점심시간(12:30) 직전에 끝나지 않음
    const day = assembleDay({
      date: "2026-09-14",
      weekday: 1,
      city: "테스트",
      pois: [poiFact({ name: "A", location: loc }), poiFact({ name: "B", location: loc }), poiFact({ name: "C", location: loc })],
      legMinutes: [0, 14, 2],
      legMode: "transit",
      legEstimated: true,
      legSource: "est",
      lunch: foodFact({ name: "점심집", location: loc }),
      dinner: foodFact({ name: "저녁집", location: loc }),
    });
    // 시간대(분) 파싱해 항목들이 서로 겹치지 않는지 검사
    const toMin = (t: string) => Number(t.slice(0, 2)) * 60 + Number(t.slice(3, 5));
    const spans = day.items.map((i) => [toMin(i.start), toMin(i.end)] as const).sort((a, b) => a[0] - b[0]);
    for (let i = 1; i < spans.length; i++) {
      expect(spans[i]![0]).toBeGreaterThanOrEqual(spans[i - 1]![1]); // 시작 >= 직전 종료
    }
    expect(day.items.some((i) => i.kind === "food" && i.name === "점심집")).toBe(true);
  });

  it("POI 가 없어도 점심·저녁이 모두 배치된다(식사시간대 미도달 폴백)", () => {
    const day = assembleDay({
      date: "2026-09-14",
      weekday: 1,
      city: "테스트",
      pois: [],
      legMinutes: [],
      legMode: "transit",
      legEstimated: true,
      legSource: "est",
      lunch: foodFact({ name: "점심집", location: loc }),
      dinner: foodFact({ name: "저녁집", location: loc }),
    });
    expect(day.items.filter((i) => i.kind === "food").map((i) => i.name)).toEqual(["점심집", "저녁집"]);
  });
});

describe("summarize", () => {
  it("high 비율을 계산한다", () => {
    const s = summarize([
      poiFact({ name: "a", location: loc }), // medium
      verified<Poi>({
        value: { name: "b", location: loc },
        confidence: "high",
        sources: [...twoSources(), { name: "c", url: "https://c.gov/", tier: 1, retrieved_at: nowISO() }],
        verification: { passes_completed: 3, agree_count: 3, checked_at: nowISO() },
      }),
      unverified<Poi>("확인 필요"),
    ]);
    expect(s).toMatchObject({ high: 1, medium: 1, low: 1, total: 3 });
  });
});
