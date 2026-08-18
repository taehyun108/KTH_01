import { describe, it, expect, vi, beforeEach } from "vitest";

// fetchJson 을 목킹해 한국어 우선 로직을 네트워크 없이 검증
const { fetchJson } = vi.hoisted(() => ({ fetchJson: vi.fn() }));
vi.mock("@/lib/http", () => ({ fetchJson, nowISO: () => "t" }));

import { wikiDescriptions } from "@/agents/fetchers/wiki-desc";

beforeEach(() => fetchJson.mockReset());

describe("wikiDescriptions 한국어 우선", () => {
  it("영문 문서의 한국어판이 있으면 한국어 요약을 쓴다", async () => {
    fetchJson.mockImplementation(async (url?: string) => {
      if (url?.includes("en.wikipedia.org")) {
        return {
          query: {
            pages: {
              "1": {
                title: "Osaka Castle",
                extract: "Osaka Castle is a Japanese castle in Osaka.",
                description: "castle in Osaka",
                langlinks: [{ lang: "ko", "*": "오사카성" }],
              },
            },
          },
        };
      }
      // ko.wikipedia
      return {
        query: { pages: { "9": { title: "오사카성", extract: "오사카성은 일본 오사카시에 있는 성이다." } } },
      };
    });

    const map = await wikiDescriptions(["Osaka Castle"]);
    expect(map.get("Osaka Castle")?.extract).toBe("오사카성은 일본 오사카시에 있는 성이다.");
  });

  it("⭐ 배치의 '모든' 문서가 한국어 설명을 받는다 (lllimit=max 회귀)", async () => {
    // lllimit=1 이던 버그: 배치 전체에서 langlink 가 1개만 와서 나머지가 영어로 폴백됐다.
    const titles = ["Belém Tower", "Jerónimos Monastery", "São Jorge Castle"];
    const koOf: Record<string, string> = {
      "Belém Tower": "벨렝 탑",
      "Jerónimos Monastery": "제로니무스 수도원",
      "São Jorge Castle": "상 조르즈 성",
    };
    fetchJson.mockImplementation(async (url?: string) => {
      if (url?.includes("en.wikipedia.org")) {
        // lllimit=max 를 보내야 문서마다 langlinks 를 준다(=이 목킹의 전제)
        expect(url).toContain("lllimit=max");
        return {
          query: {
            pages: Object.fromEntries(
              titles.map((t, i) => [
                String(i),
                { title: t, extract: `${t} is a landmark.`, langlinks: [{ lang: "ko", "*": koOf[t]! }] },
              ]),
            ),
          },
        };
      }
      return {
        query: {
          pages: Object.fromEntries(
            Object.values(koOf).map((k, i) => [String(i), { title: k, extract: `${k}은 리스본의 명소이다.` }]),
          ),
        },
      };
    });

    const map = await wikiDescriptions(titles);
    for (const t of titles) {
      expect(map.get(t)?.extract).toBe(`${koOf[t]}은 리스본의 명소이다.`);
      expect(map.get(t)?.title_ko).toBe(koOf[t]); // 장소명 한국어 표기도 제공
    }
  });

  it("한국어판이 없으면 영어 요약으로 폴백", async () => {
    fetchJson.mockImplementation(async (url?: string) => {
      if (url?.includes("en.wikipedia.org")) {
        return {
          query: {
            pages: { "1": { title: "Tiny Local Park", extract: "A small local park." } },
          },
        };
      }
      return { query: { pages: {} } };
    });

    const map = await wikiDescriptions(["Tiny Local Park"]);
    expect(map.get("Tiny Local Park")?.extract).toBe("A small local park.");
  });
});
