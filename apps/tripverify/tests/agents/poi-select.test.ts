import { describe, it, expect } from "vitest";
import {
  conceptBuckets,
  classifyTags,
  notableFromTags,
  scoreSeed,
  selectPois,
  inferCategoriesFromTitle,
  wikiFallbackSeeds,
  mergeByProximity,
  isDefunctDescription,
  inferAllDay,
} from "@/agents/poi-select";
import type { PoiSeed, WikiArticle } from "@/agents/poi-build";

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

describe("Wikipedia 기반 POI (클라우드 안정 소스)", () => {
  it("inferCategoriesFromTitle: 제목에서 카테고리 추론", () => {
    expect(inferCategoriesFromTitle("Osaka Castle")).toContain("history");
    expect(inferCategoriesFromTitle("Shitennoji Temple")).toContain("religious");
    expect(inferCategoriesFromTitle("Tsutenkaku Tower")).toContain("view");
    expect(inferCategoriesFromTitle("Tennoji Zoo")).toContain("family");
  });

  it("wikiFallbackSeeds: 역/학교 등 비관광 문서는 제외, 명소는 notable", () => {
    const wiki: WikiArticle[] = [
      { title: "Osaka Castle", location: { lat: 34.6873, lng: 135.5259 } },
      { title: "Osaka Station", location: { lat: 34.7, lng: 135.5 } }, // 제외
      { title: "Kyoto University", location: { lat: 35.02, lng: 135.78 } }, // 제외
    ];
    const seeds = wikiFallbackSeeds(wiki);
    expect(seeds.map((s) => s.name)).toEqual(["Osaka Castle"]);
    expect(seeds[0]!.notable).toBe(true);
    expect(seeds[0]!.origin).toBe("wiki");
  });

  it("mergeByProximity: OSM 우선, 근접 중복 위키 제거", () => {
    const osm: PoiSeed[] = [{ name: "성(OSM)", location: { lat: 34.6873, lng: 135.5259 }, origin: "osm" }];
    const wikiSeeds: PoiSeed[] = [
      { name: "성(Wiki)", location: { lat: 34.6874, lng: 135.526 }, origin: "wiki" }, // 근접 중복
      { name: "먼 명소", location: { lat: 34.70, lng: 135.55 }, origin: "wiki" },
    ];
    const merged = mergeByProximity(osm, wikiSeeds);
    expect(merged.map((m) => m.name)).toEqual(["성(OSM)", "먼 명소"]);
    expect(merged[0]!.on_osm).toBe(true);
    expect(merged[1]!.on_osm).toBe(false);
  });

  it("isDefunctDescription: 폐관/철거 설명 감지", () => {
    expect(isDefunctDescription("A former museum, closed in 2014")).toBe(true);
    expect(isDefunctDescription("A famous castle in Osaka")).toBe(false);
    expect(isDefunctDescription(undefined)).toBe(false);
  });

  it("inferAllDay: 테마파크 종일 판별", () => {
    expect(inferAllDay("Universal Studios Japan", ["activity"])).toBe(true);
    expect(inferAllDay("Osaka Castle", ["history"])).toBe(false);
  });

  it("scoreSeed: OSM 존재(구글검색 가능)를 강하게 우대", () => {
    const pref = conceptBuckets(undefined, ["history"]);
    const onOsm = { name: "a", location: loc, categories: ["history"], notable: true, on_osm: true };
    const noOsm = { name: "b", location: loc, categories: ["history"], notable: true, on_osm: false };
    expect(scoreSeed(onOsm, pref, false)).toBeGreaterThan(scoreSeed(noOsm, pref, false));
  });
});
