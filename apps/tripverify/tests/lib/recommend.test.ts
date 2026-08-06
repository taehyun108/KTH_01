import { describe, it, expect } from "vitest";
import { cuisineDishes, recommendReason, menuHint } from "@/lib/recommend";
import { timePrefFromCategories } from "@/agents/poi-select";
import type { Poi, Restaurant } from "@/core/types/domains";

describe("cuisineDishes / menuHint", () => {
  it("cuisine 태그 → 대표 요리", () => {
    expect(cuisineDishes("ramen")).toBe("라멘");
    expect(cuisineDishes("sushi;ramen")).toBe("스시·사시미, 라멘");
    expect(cuisineDishes("")).toBe("");
    expect(cuisineDishes("unknown_xyz")).toBe("");
  });
  it("menuHint 은 cuisine 없으면 null", () => {
    expect(menuHint({ name: "x", location: { lat: 0, lng: 0 } } as Restaurant)).toBeNull();
    expect(menuHint({ name: "x", location: { lat: 0, lng: 0 }, cuisine: "udon" } as Restaurant)).toBe("우동");
  });
});

describe("recommendReason", () => {
  it("식당: 대표 요리 + 가격대", () => {
    const r: Restaurant = { name: "라멘집", location: { lat: 0, lng: 0 }, cuisine: "ramen", price_level: 2 };
    const reason = recommendReason(r, "food", "low");
    expect(reason).toContain("라멘 전문");
    expect(reason).toContain("중간 가격대");
  });
  it("POI: 카테고리 + 감수성 + 교차검증", () => {
    const p: Poi = { name: "타워", location: { lat: 0, lng: 0 }, categories: ["view"], time_pref: "evening" };
    const reason = recommendReason(p, "poi", "medium");
    expect(reason).toContain("전망 명소");
    expect(reason).toContain("야경");
    expect(reason).toContain("교차검증");
  });

  it("POI: Wikipedia 설명이 있으면 구체적 사유로 사용", () => {
    const p: Poi = {
      name: "Osaka Castle",
      location: { lat: 0, lng: 0 },
      categories: ["history"],
      description: "Osaka Castle is one of Japan's most famous landmarks.",
    };
    const reason = recommendReason(p, "poi", "medium");
    expect(reason).toContain("most famous landmarks");
    expect(reason).toContain("[역사]");
  });
});

describe("timePrefFromCategories (감수성)", () => {
  it("전망=저녁, 시장=오전, 그 외=주간", () => {
    expect(timePrefFromCategories(["view"])).toBe("evening");
    expect(timePrefFromCategories(["shopping"])).toBe("morning");
    expect(timePrefFromCategories(["history"])).toBe("day");
    expect(timePrefFromCategories([])).toBe("day");
  });
});
