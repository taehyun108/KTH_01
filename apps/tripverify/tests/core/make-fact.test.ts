import { describe, it, expect } from "vitest";
import { z } from "zod";
import { verified, unverified, reviveFact } from "@/core/factory/make-fact";
import { isRenderable } from "@/core/types/verified-fact";
import { judgeConfidence } from "@/core/verification/protocol";
import { CurrencyInfoSchema } from "@/core/schema/domains.schema";

const nowISO = () => new Date().toISOString();
const src = (tier: 1 | 2 | 3, host: string) => ({
  name: `src-${host}`,
  url: `https://${host}/`,
  tier,
  retrieved_at: nowISO(),
});

describe("make-fact 팩토리 불변식 (§4)", () => {
  it("unverified 는 value=null / confidence=low / 사유 동반", () => {
    const f = unverified<number>("출처 3곳 미확보");
    expect(f.value).toBeNull();
    expect(f.confidence).toBe("low");
    expect(f.unverified_reason).toBe("출처 3곳 미확보");
    expect(isRenderable(f)).toBe(false);
  });

  it("verified(high, 출처 3개) 는 렌더 가능", () => {
    const f = verified<number>({
      value: 9.31,
      confidence: "high",
      sources: [src(1, "a.com"), src(2, "b.org"), src(1, "c.gov")],
      verification: { passes_completed: 3, agree_count: 3, checked_at: nowISO() },
    });
    expect(isRenderable(f)).toBe(true);
    if (isRenderable(f)) {
      // 타입 가드 통과 후 value 는 number 로 좁혀진다.
      expect(f.value.toFixed(2)).toBe("9.31");
    }
  });

  it("verified(medium, 출처 1개) 는 스키마에서 throw", () => {
    expect(() =>
      verified<number>({
        value: 1,
        confidence: "medium",
        sources: [src(1, "a.com")],
        verification: { passes_completed: 2, agree_count: 2, checked_at: nowISO() },
      }),
    ).toThrow();
  });

  it("low 는 값이 있어도 isRenderable=false (§3 값 숨김)", () => {
    const f = verified<number>({
      value: 123,
      confidence: "low",
      sources: [src(3, "blog.com")],
      verification: { passes_completed: 1, agree_count: 1, checked_at: nowISO() },
    });
    expect(isRenderable(f)).toBe(false);
  });

  it("reviveFact 는 JSON 을 값 스키마로 검증하며 복원한다", () => {
    const raw = {
      value: { code: "JPY", krw_per_unit: 9.31, base: "KRW" },
      confidence: "high",
      sources: [src(1, "a.com"), src(2, "b.org"), src(1, "c.gov")],
      verification: { passes_completed: 3, agree_count: 3, checked_at: nowISO() },
    };
    const f = reviveFact(CurrencyInfoSchema, raw);
    expect(f.value?.code).toBe("JPY");
  });

  it("reviveFact 는 잘못된 값을 거부한다", () => {
    expect(() =>
      reviveFact(z.number(), {
        value: "not-a-number",
        confidence: "low",
        sources: [src(3, "blog.com")],
        verification: { passes_completed: 1, agree_count: 1, checked_at: nowISO() },
      }),
    ).toThrow();
  });
});

describe("judgeConfidence 판정 규칙 (§3)", () => {
  it("agree>=3 & 편차 허용 → high", () => {
    expect(judgeConfidence({ agree_count: 3, deviation: 0.001, tolerance: 0.005 })).toBe("high");
  });
  it("agree>=3 이지만 편차 초과 → high 아님(=low)", () => {
    expect(judgeConfidence({ agree_count: 3, deviation: 0.02, tolerance: 0.005 })).toBe("low");
  });
  it("agree==2 → medium", () => {
    expect(judgeConfidence({ agree_count: 2 })).toBe("medium");
  });
  it("agree<2 → low", () => {
    expect(judgeConfidence({ agree_count: 1 })).toBe("low");
  });
  it("비수치형(편차 없음) & agree>=3 → high", () => {
    expect(judgeConfidence({ agree_count: 3 })).toBe("high");
  });
});
