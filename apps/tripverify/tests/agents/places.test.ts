import { describe, it, expect } from "vitest";
import { poiAgent, foodAgent } from "@/agents/poi-agent";
import type { SourceReader } from "@/agents/types";
import type { Poi, Restaurant, GeoPoint } from "@/core/types/domains";
import type { PlaceArgs } from "@/agents/fetchers/places";
import { isRenderable } from "@/core/types/verified-fact";

/** 합성 테스트 더블 — 검증 로직 확인용. 실 데이터 아님(§0). */
const center: GeoPoint = { lat: 34.6873, lng: 135.5259 };
const src = (host: string, tier: 1 | 2 | 3) => ({
  name: host,
  url: `https://${host}/`,
  tier,
  retrieved_at: "2026-08-02T00:00:00Z",
});

/** 지정 장소를 지정 좌표로 반환하는 리더. offsetM 로 좌표를 흔든다. */
function poiReaderAt(
  host: string,
  tier: 1 | 2 | 3,
  offsetDeg = 0,
): SourceReader<PlaceArgs, Poi> {
  return async ({ name, center }) => [
    {
      value: { name, location: { lat: center.lat + offsetDeg, lng: center.lng } },
      source: src(host, tier),
      pass: tier === 1 ? 1 : 2,
    },
  ];
}

describe("poi-agent — 실존/위치 교차검증 (§10)", () => {
  it("2독립 출처가 100m 이내 동일 좌표 → medium (표시 가능)", async () => {
    const facts = await poiAgent(["오사카성"], { center }, [
      poiReaderAt("overpass-api.de", 2),
      poiReaderAt("en.wikipedia.org", 2, 0.0005), // ~55m
    ]);
    expect(facts[0]!.confidence).toBe("medium");
    expect(isRenderable(facts[0]!)).toBe(true);
    expect(facts[0]!.value?.name).toBe("오사카성");
  });

  it("단일 출처만 → low (유령 장소 방지: 일정에서 제외됨)", async () => {
    const facts = await poiAgent(["수상한장소"], { center }, [
      poiReaderAt("overpass-api.de", 2),
    ]);
    expect(facts[0]!.confidence).toBe("low");
    expect(isRenderable(facts[0]!)).toBe(false);
  });

  it("좌표가 100m 초과로 어긋나면 서로 상충 → low", async () => {
    const facts = await poiAgent(["애매한장소"], { center }, [
      poiReaderAt("overpass-api.de", 2),
      poiReaderAt("en.wikipedia.org", 2, 0.01), // ~1.1km → 불일치
    ]);
    expect(facts[0]!.confidence).toBe("low");
    expect(facts[0]!.verification.conflicting_values?.length).toBe(1);
  });

  it("조회 실패 장소 → unverified", async () => {
    const empty: SourceReader<PlaceArgs, Poi> = async () => [];
    const facts = await poiAgent(["없는곳"], { center }, [empty, empty]);
    expect(facts[0]!.value).toBeNull();
  });
});

describe("food-agent", () => {
  it("2독립 출처 근접 좌표 → medium", async () => {
    const r = (host: string, tier: 1 | 2 | 3, off = 0): SourceReader<PlaceArgs, Restaurant> =>
      async ({ name, center }) => [
        {
          value: { name, location: { lat: center.lat + off, lng: center.lng } },
          source: src(host, tier),
          pass: tier === 1 ? 1 : 2,
        },
      ];
    const facts = await foodAgent(["쿠시카츠집"], { center }, [
      r("overpass-api.de", 2),
      r("tripadvisor.com", 2, 0.0003),
    ]);
    expect(facts[0]!.confidence).toBe("medium");
  });
});
