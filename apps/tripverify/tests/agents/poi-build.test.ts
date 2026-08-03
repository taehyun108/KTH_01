import { describe, it, expect } from "vitest";
import { buildPoiFacts, buildRestaurantFacts, type PoiSeed, type WikiArticle } from "@/agents/poi-build";
import { hasSourcedValue } from "@/core/types/verified-fact";

const NOW = Date.parse("2026-08-03T00:00:00Z");
const osaka = { lat: 34.6873, lng: 135.5259 };

describe("buildPoiFacts (라이브 POI 구성)", () => {
  const seeds: PoiSeed[] = [
    { name: "Osaka Castle", location: osaka, opening_hours: ["Mo-Su 09:00-17:00"], admission_fee_local: 600 },
  ];

  it("OSM 단일 출처 → low 이지만 값·출처가 있어 표시 가능(§0)", () => {
    const facts = buildPoiFacts(seeds, [], NOW);
    expect(facts.length).toBe(1);
    expect(facts[0]!.confidence).toBe("low");
    expect(hasSourcedValue(facts[0]!)).toBe(true); // 표시됨
    expect(facts[0]!.value?.name).toBe("Osaka Castle");
    expect(facts[0]!.sources[0]!.url).toContain("overpass");
  });

  it("Wikipedia 가 100m 내에서 확인되면 medium 으로 승격", () => {
    const wiki: WikiArticle[] = [
      { title: "Osaka Castle", location: { lat: 34.6875, lng: 135.5261 } }, // ~30m
    ];
    const facts = buildPoiFacts(seeds, wiki, NOW);
    expect(facts[0]!.confidence).toBe("medium");
    expect(facts[0]!.verification.agree_count).toBe(2);
  });

  it("멀리 있는 Wikipedia 문서는 승격에 쓰이지 않는다", () => {
    const wiki: WikiArticle[] = [
      { title: "Somewhere", location: { lat: 34.70, lng: 135.55 } }, // >1km
    ];
    const facts = buildPoiFacts(seeds, wiki, NOW);
    expect(facts[0]!.confidence).toBe("low");
  });

  it("이름 재조회 버그 없음: 발굴 좌표를 그대로 사용", () => {
    const jp: PoiSeed[] = [{ name: "通天閣", location: { lat: 34.6525, lng: 135.5063 } }];
    const facts = buildPoiFacts(jp, [], NOW);
    expect(facts[0]!.value?.location.lat).toBeCloseTo(34.6525, 3);
  });
});

describe("buildRestaurantFacts", () => {
  it("OSM 식당 → low(표시됨), 가격대 보존", () => {
    const facts = buildRestaurantFacts(
      [{ name: "Kushikatsu Daruma", location: osaka, price_level: 2 }],
      NOW,
    );
    expect(facts[0]!.confidence).toBe("low");
    expect(hasSourcedValue(facts[0]!)).toBe(true);
    expect(facts[0]!.value?.price_level).toBe(2);
  });
});
