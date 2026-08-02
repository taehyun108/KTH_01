import { describe, it, expect } from "vitest";
import {
  VerifiedFactSchema,
  verifiedFactSchema,
} from "@/core/schema/verified-fact.schema";
import { CurrencyInfoSchema } from "@/core/schema/domains.schema";

const nowISO = () => new Date().toISOString();

const src = (tier: 1 | 2 | 3, host: string) => ({
  name: `src-${host}`,
  url: `https://${host}/`,
  tier,
  retrieved_at: nowISO(),
});

const verification = () => ({
  passes_completed: 3 as const,
  agree_count: 3,
  checked_at: nowISO(),
});

describe("VerifiedFactSchema 불변식 (§0/§3/§4)", () => {
  it("출처 없는 값은 거부한다 (§0-3)", () => {
    const r = VerifiedFactSchema.safeParse({
      value: 100,
      confidence: "high",
      sources: [],
      verification: verification(),
    });
    expect(r.success).toBe(false);
  });

  it("value=null 인데 사유가 없으면 거부한다 (§0-4)", () => {
    const r = VerifiedFactSchema.safeParse({
      value: null,
      confidence: "low",
      sources: [],
      verification: { passes_completed: 1, agree_count: 0, checked_at: nowISO() },
    });
    expect(r.success).toBe(false);
  });

  it("value=null + 사유는 통과한다 (§0-4)", () => {
    const r = VerifiedFactSchema.safeParse({
      value: null,
      confidence: "low",
      sources: [],
      verification: { passes_completed: 1, agree_count: 0, checked_at: nowISO() },
      unverified_reason: "독립 출처 3곳 미확보",
    });
    expect(r.success).toBe(true);
  });

  it("confidence=medium 인데 출처가 1개면 거부한다 (§3)", () => {
    const r = VerifiedFactSchema.safeParse({
      value: 100,
      confidence: "medium",
      sources: [src(1, "a.com")],
      verification: { passes_completed: 2, agree_count: 2, checked_at: nowISO() },
    });
    expect(r.success).toBe(false);
  });

  it("confidence=high + 출처 3개는 통과한다 (§3)", () => {
    const r = VerifiedFactSchema.safeParse({
      value: 100,
      confidence: "high",
      sources: [src(1, "a.com"), src(2, "b.org"), src(1, "c.gov")],
      verification: verification(),
    });
    expect(r.success).toBe(true);
  });

  it("잘못된 URL 출처는 거부한다 (§0-3)", () => {
    const r = VerifiedFactSchema.safeParse({
      value: 100,
      confidence: "medium",
      sources: [
        { name: "x", url: "not-a-url", tier: 1, retrieved_at: nowISO() },
        src(2, "b.org"),
      ],
      verification: { passes_completed: 2, agree_count: 2, checked_at: nowISO() },
    });
    expect(r.success).toBe(false);
  });

  it("retrieved_at 이 ISO8601 이 아니면 거부한다 (§4)", () => {
    const r = VerifiedFactSchema.safeParse({
      value: 100,
      confidence: "low",
      sources: [{ name: "x", url: "https://a.com/", tier: 1, retrieved_at: "2026/08/02" }],
      verification: { passes_completed: 1, agree_count: 1, checked_at: nowISO() },
      unverified_reason: "n/a",
    });
    expect(r.success).toBe(false);
  });

  it("excerpt 30자 초과는 거부한다 (§4)", () => {
    const r = VerifiedFactSchema.safeParse({
      value: 100,
      confidence: "low",
      sources: [
        {
          name: "x",
          url: "https://a.com/",
          tier: 1,
          retrieved_at: nowISO(),
          excerpt: "가".repeat(31),
        },
      ],
      verification: { passes_completed: 1, agree_count: 1, checked_at: nowISO() },
      unverified_reason: "n/a",
    });
    expect(r.success).toBe(false);
  });
});

describe("도메인 값 스키마 결합", () => {
  it("CurrencyInfo 값을 감싼 FACT 를 검증한다", () => {
    const schema = verifiedFactSchema(CurrencyInfoSchema);
    const r = schema.safeParse({
      value: { code: "JPY", krw_per_unit: 9.31, base: "KRW" },
      confidence: "high",
      sources: [src(1, "a.com"), src(2, "b.org"), src(1, "c.gov")],
      verification: verification(),
    });
    expect(r.success).toBe(true);
  });

  it("잘못된 통화 코드(2자리)는 거부한다", () => {
    const schema = verifiedFactSchema(CurrencyInfoSchema);
    const r = schema.safeParse({
      value: { code: "JP", krw_per_unit: 9.31, base: "KRW" },
      confidence: "high",
      sources: [src(1, "a.com"), src(2, "b.org"), src(1, "c.gov")],
      verification: verification(),
    });
    expect(r.success).toBe(false);
  });
});
