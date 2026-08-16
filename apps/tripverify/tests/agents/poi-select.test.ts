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
  isVisitorAttraction,
  fameScore,
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

  it("isDefunctDescription: 'was an ...' 철거 타워도 감지", () => {
    expect(
      isDefunctDescription("Osaka Tower was an observation and radio tower built beside the ABC headquarters."),
    ).toBe(true);
  });

  it("isVisitorAttraction: 아파트/주거 건물은 이름에 tower 가 있어도 제외", () => {
    expect(
      isVisitorAttraction({
        name: "The Tower Osaka",
        location: loc,
        origin: "wiki",
        description: "The Tower Osaka is a high rise apartment building situated at Fukushima-ku, Osaka.",
      }),
    ).toBe(false);
    expect(
      isVisitorAttraction({
        name: "City Tower Nishi-Umeda",
        location: loc,
        origin: "wiki",
        description: "City Tower Nishi-Umeda is a high rise apartment building.",
      }),
    ).toBe(false);
  });

  it("inferAllDay: 테마파크 종일 판별", () => {
    expect(inferAllDay("Universal Studios Japan", ["activity"])).toBe(true);
    expect(inferAllDay("Osaka Castle", ["history"])).toBe(false);
  });

  it("isVisitorAttraction: 관공서/기업만 제외, 기본 허용", () => {
    // 정부기관(설명에 government/agency) → 제외
    expect(
      isVisitorAttraction({
        name: "Small and Medium Enterprise Administration",
        location: loc,
        origin: "wiki",
        description: "a government agency of Taiwan",
      }),
    ).toBe(false);
    // 일본식 이름 사찰(설명·카테고리 없어도) → 포함(기본 허용)
    expect(isVisitorAttraction({ name: "Kinkaku-ji", location: loc, origin: "wiki" })).toBe(true);
    expect(isVisitorAttraction({ name: "Fushimi Inari-taisha", location: loc, origin: "wiki" })).toBe(true);
  });

  it("inferCategoriesFromTitle: 일본식 접미사(-ji/-dera/-taisha) 인식", () => {
    expect(inferCategoriesFromTitle("Kinkaku-ji")).toContain("religious");
    expect(inferCategoriesFromTitle("Kiyomizu-dera")).toContain("religious");
    expect(inferCategoriesFromTitle("Fushimi Inari-taisha")).toContain("religious");
    expect(inferCategoriesFromTitle("Nijo Castle")).toContain("history");
  });

  it("inferCategoriesFromTitle: 테마파크(유니버설/디즈니)를 activity·family 로 인식", () => {
    expect(inferCategoriesFromTitle("Universal Studios Japan")).toEqual(
      expect.arrayContaining(["activity", "family"]),
    );
    expect(inferCategoriesFromTitle("Tokyo Disneyland")).toEqual(
      expect.arrayContaining(["activity", "family"]),
    );
  });

  it("⭐ 마퀴 명소(유니버설)는 기본 컨셉에서도 무명 명소보다 훨씬 상위·선별된다", () => {
    const usj = seed({
      name: "Universal Studios Japan",
      categories: ["activity", "family"],
      notable: true,
    });
    const shrine = seed({ name: "작은 신사", categories: ["religious"], notable: true });
    expect(fameScore(usj)).toBeGreaterThan(fameScore(shrine));
    // 스타일/컨셉을 안 줘도 상위 선별에 포함
    const picked = selectPois([shrine, usj], [], { styles: [], limit: 1 });
    expect(picked.map((p) => p.name)).toContain("Universal Studios Japan");
  });

  it("⭐ 바르셀로나: 사그라다 파밀리아가 1순위로 정렬된다(아이코닉 랜드마크)", () => {
    // 바르셀로나 대표 후보들(현실적 설명 포함). 모두 유명·OSM 존재.
    const sagrada = seed({
      name: "Sagrada Família",
      name_en: "Sagrada Família",
      categories: ["religious", "history"],
      notable: true,
      on_osm: true,
      description:
        "The Sagrada Família is a large unfinished basilica and one of the most famous landmarks in Barcelona, a UNESCO World Heritage Site and the most visited monument in Spain.",
    });
    const parkGuell = seed({
      name: "Park Güell",
      categories: ["nature", "art"],
      notable: true,
      on_osm: true,
      description: "Park Güell is a famous public park designed by Antoni Gaudí, a popular landmark.",
    });
    const museum = seed({
      name: "Museu Picasso",
      categories: ["history", "art"],
      notable: true,
      on_osm: true,
      description: "An art museum dedicated to Pablo Picasso.",
    });
    const obscure = seed({ name: "작은 지역 성당", categories: ["religious"], notable: true, on_osm: false });

    // 최종 표시 순서는 fameScore(collectPois 재정렬) — 사그라다가 1순위
    const ranked = [obscure, museum, parkGuell, sagrada].sort((a, b) => fameScore(b) - fameScore(a));
    expect(ranked[0]!.name).toBe("Sagrada Família");
    expect(fameScore(sagrada)).toBeGreaterThan(fameScore(parkGuell));

    // 후보 선별(컨셉/스타일 미지정)에도 반드시 포함(무명은 뒤로)
    const picked = selectPois([obscure, museum, parkGuell, sagrada], [], { styles: [], limit: 3 });
    expect(picked.map((p) => p.name)).toContain("Sagrada Família");
    expect(picked.map((p) => p.name)).not.toContain("작은 지역 성당");
  });

  it("fameScore: 유명 명소(긴 설명·OSM·유명키워드)가 무명보다 상위", () => {
    const famous = {
      name: "Osaka Castle",
      location: loc,
      on_osm: true,
      notable: true,
      categories: ["history"],
      description:
        "Osaka Castle is one of Japan's most famous landmarks and a major tourist attraction, playing a major role in the unification of Japan.",
    };
    const obscure = {
      name: "Ikukunitama Shrine",
      location: loc,
      notable: true,
      categories: ["religious"],
      description: "A shrine in Osaka.",
    };
    expect(fameScore(famous)).toBeGreaterThan(fameScore(obscure));
  });

  it("scoreSeed: OSM 존재(구글검색 가능)를 강하게 우대", () => {
    const pref = conceptBuckets(undefined, ["history"]);
    const onOsm = { name: "a", location: loc, categories: ["history"], notable: true, on_osm: true };
    const noOsm = { name: "b", location: loc, categories: ["history"], notable: true, on_osm: false };
    expect(scoreSeed(onOsm, pref, false)).toBeGreaterThan(scoreSeed(noOsm, pref, false));
  });
});
