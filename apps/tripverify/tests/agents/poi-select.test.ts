import { describe, it, expect } from "vitest";
import {
  conceptBuckets,
  classifyTags,
  notableFromTags,
  scoreSeed,
  selectPois,
} from "@/agents/poi-select";
import type { PoiSeed } from "@/agents/poi-build";

const loc = { lat: 34.7, lng: 135.5 };
const seed = (over: Partial<PoiSeed>): PoiSeed => ({
  name: "x",
  location: loc,
  categories: [],
  notable: false,
  ...over,
});

describe("classifyTags / notableFromTags", () => {
  it("OSM 태그를 카테고리로 분류", () => {
    expect(classifyTags({ historic: "castle" })).toContain("history");
    expect(classifyTags({ tourism: "museum" })).toContain("history");
    expect(classifyTags({ leisure: "park" })).toContain("nature");
    expect(classifyTags({ amenity: "place_of_worship" })).toContain("religious");
    expect(classifyTags({ tourism: "viewpoint" })).toContain("view");
  });
  it("위키데이터 태그 → 유명", () => {
    expect(notableFromTags({ wikidata: "Q123" })).toBe(true);
    expect(notableFromTags({})).toBe(false);
  });
});

describe("conceptBuckets", () => {
  it("자유 문구 키워드를 버킷으로", () => {
    expect(conceptBuckets("역사와 사찰 중심", [])).toContain("history");
    expect(conceptBuckets("역사와 사찰 중심", [])).toContain("religious");
    expect(conceptBuckets("미식 투어", [])).toContain("food");
    expect(conceptBuckets("자연 힐링", [])).toContain("nature");
  });
  it("스타일도 반영", () => {
    expect(conceptBuckets(undefined, ["food"])).toContain("food");
    expect(conceptBuckets(undefined, ["activity"])).toContain("activity");
  });
});

describe("scoreSeed / selectPois", () => {
  const pref = conceptBuckets("역사 중심", ["history"]);

  it("유명 + 컨셉일치가 높은 점수", () => {
    const famous = seed({ name: "유명 성", categories: ["history"], notable: true });
    const obscure = seed({ name: "하수도 박물관", categories: ["history"], notable: false });
    expect(scoreSeed(famous, pref, false)).toBeGreaterThan(scoreSeed(obscure, pref, false));
  });

  it("컨셉과 무관하고 무명이면 제외(score<=0)", () => {
    const offTopic = seed({ name: "동네 상점", categories: ["shopping"], notable: false });
    const picked = selectPois([offTopic], [], { concept: "역사 중심", styles: ["history"], limit: 5 });
    expect(picked.length).toBe(0);
  });

  it("유명·관련 장소가 상위로 선별되고 limit 로 자른다", () => {
    const seeds = [
      seed({ name: "하수도 박물관", categories: ["history"], notable: false }),
      seed({ name: "유명 성", categories: ["history"], notable: true }),
      seed({ name: "대형 사찰", categories: ["religious", "history"], notable: true }),
      seed({ name: "동네 상점", categories: ["shopping"], notable: false }),
    ];
    const picked = selectPois(seeds, [], { concept: "역사와 사찰", styles: ["history"], limit: 2 });
    expect(picked.length).toBe(2);
    expect(picked.map((p) => p.name)).toContain("유명 성");
    expect(picked.map((p) => p.name)).toContain("대형 사찰");
    expect(picked.map((p) => p.name)).not.toContain("동네 상점");
  });
});
