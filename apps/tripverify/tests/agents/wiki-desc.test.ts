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
