import { describe, it, expect } from "vitest";
import { verify } from "@/core/verification/verifier";
import {
  numericRatio,
  geoWithin,
  exact,
  type Observation,
} from "@/core/verification/observation";
import type { Source } from "@/core/types/verified-fact";
import type { GeoPoint } from "@/core/types/domains";
import { isRenderable } from "@/core/types/verified-fact";

const T0 = Date.parse("2026-08-02T00:00:00Z");
function src(host: string, tier: 1 | 2 | 3, offsetSec = 0): Source {
  return {
    name: host,
    url: `https://${host}/`,
    tier,
    retrieved_at: new Date(T0 + offsetSec * 1000).toISOString(),
  };
}
const obs = <T>(value: T, source: Source, pass: 1 | 2 | 3): Observation<T> => ({
  value,
  source,
  pass,
});

describe("verify — 수치형 (환율/가격)", () => {
  const cfg = { comparator: numericRatio(0.005), tolerance: 0.005, requireTimeSeparation: true };

  it("독립 3출처 동의 + 60s 시간차 → high", () => {
    const f = verify<number>(
      [
        obs(9.31, src("koreaexim.go.kr", 1, 0), 1),
        obs(9.315, src("ecb.europa.eu", 1, 30), 2),
        obs(9.312, src("exchangerate.host", 2, 90), 3), // 90s 후 재조회 → 시간차 충족
      ],
      cfg,
    );
    expect(f.confidence).toBe("high");
    expect(f.verification.agree_count).toBe(3);
    expect(f.verification.passes_completed).toBe(3);
    expect(isRenderable(f)).toBe(true);
  });

  it("2출처만 동의 → medium", () => {
    const f = verify<number>(
      [
        obs(9.31, src("koreaexim.go.kr", 1, 0), 1),
        obs(9.315, src("ecb.europa.eu", 1, 90), 2),
      ],
      cfg,
    );
    expect(f.confidence).toBe("medium");
    expect(f.verification.agree_count).toBe(2);
  });

  it("1출처 → low (값 숨김)", () => {
    const f = verify<number>([obs(9.31, src("a.com", 2, 0), 1)], cfg);
    expect(f.confidence).toBe("low");
    expect(isRenderable(f)).toBe(false);
  });

  it("허용오차 초과 출처는 상충으로 분리되어 agree_count 하락", () => {
    const f = verify<number>(
      [
        obs(9.31, src("koreaexim.go.kr", 1, 0), 1),
        obs(9.315, src("ecb.europa.eu", 1, 90), 2),
        obs(11.0, src("badsource.com", 2, 120), 3), // 오차 초과 → 상충
      ],
      cfg,
    );
    expect(f.confidence).toBe("medium"); // 동의는 2곳
    expect(f.verification.conflicting_values?.length).toBe(1);
  });

  it("3출처 동의하나 시간차 없음 → high 불가(medium 강등)", () => {
    const f = verify<number>(
      [
        obs(9.31, src("a.com", 1, 0), 1),
        obs(9.31, src("b.org", 1, 0), 2),
        obs(9.31, src("c.gov", 2, 0), 3), // 모두 동일 시각
      ],
      cfg,
    );
    expect(f.confidence).toBe("medium");
  });
});

describe("verify — 출처 등급 우선 채택 (§3)", () => {
  it("공식(tier1) 값을 채택하고 블로그 값은 conflicting 에 보관", () => {
    const f = verify<number>(
      [
        obs(5000, src("official.go.jp", 1, 0), 1), // 공식
        obs(4000, src("blog1.com", 3, 90), 2),
        obs(4000, src("blog2.com", 3, 120), 3),
      ],
      { comparator: numericRatio(0.1), tolerance: 0.1 },
    );
    expect(f.value).toBe(5000); // 다수결(4000)이 아니라 공식(5000) 채택
    expect(f.verification.conflicting_values?.length).toBe(2);
  });

  it("커뮤니티(tier3) 단독 근거만이면 high 불가", () => {
    const f = verify<number>(
      [
        obs(100, src("blog1.com", 3, 0), 1),
        obs(100, src("blog2.com", 3, 90), 2),
        obs(100, src("blog3.com", 3, 180), 3),
      ],
      { comparator: numericRatio(0.1), tolerance: 0.1, requireTimeSeparation: false },
    );
    expect(f.confidence).toBe("medium"); // 권위 출처 없음 → 강등
  });
});

describe("verify — 좌표/영업시간", () => {
  it("좌표 100m 이내 3출처 → high", () => {
    const p = (lat: number, lng: number): GeoPoint => ({ lat, lng });
    const f = verify<GeoPoint>(
      [
        obs(p(34.6873, 135.5259), src("osm.org", 2, 0), 1),
        obs(p(34.6874, 135.526), src("googleapis.com", 2, 60), 2),
        obs(p(34.6872, 135.5258), src("foursquare.com", 2, 130), 3),
      ],
      { comparator: geoWithin(100) },
    );
    expect(f.confidence).toBe("high");
  });

  it("영업시간 완전 일치 2출처 → medium, 불일치 1출처는 conflicting", () => {
    const hours = ["09:00-17:00", null, "09:00-17:00"];
    const diff = ["09:00-18:00", null, "09:00-18:00"];
    const f = verify<(string | null)[]>(
      [
        obs(hours, src("official.jp", 1, 0), 1),
        obs(hours, src("osm.org", 2, 60), 2),
        obs(diff, src("blog.com", 3, 130), 3),
      ],
      { comparator: exact<(string | null)[]>() },
    );
    expect(f.value).toEqual(hours);
    expect(f.confidence).toBe("medium"); // 동의 2곳(official+osm), blog 는 상충
  });
});

describe("verify — 빈 입력", () => {
  it("관측 없음 → unverified", () => {
    const f = verify<number>([], { comparator: numericRatio(0.005) });
    expect(f.value).toBeNull();
    expect(f.confidence).toBe("low");
    expect(f.unverified_reason).toBeDefined();
  });
});
