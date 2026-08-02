import { describe, it, expect } from "vitest";
import { z } from "zod";
import { getCachedFact, putCachedFact, cachedVerify, appendAudit } from "@/db/repo";
import { getDb } from "@/db/client";
import { auditLog } from "@/db/schema";
import { verified, unverified } from "@/core/factory/make-fact";
import { CurrencyInfoSchema } from "@/core/schema/domains.schema";
import type { CurrencyInfo } from "@/core/types/domains";

const nowISO = () => new Date().toISOString();
function sampleFact(): ReturnType<typeof verified<CurrencyInfo>> {
  return verified<CurrencyInfo>({
    value: { code: "JPY", krw_per_unit: 9.31, base: "KRW" },
    confidence: "high",
    sources: [
      { name: "a", url: "https://a.com/", tier: 1, retrieved_at: nowISO() },
      { name: "b", url: "https://b.org/", tier: 2, retrieved_at: nowISO() },
      { name: "c", url: "https://c.gov/", tier: 1, retrieved_at: nowISO() },
    ],
    verification: { passes_completed: 3, agree_count: 3, checked_at: nowISO() },
  });
}

describe("fact_cache 저장/조회 (§7)", () => {
  it("put 후 get 으로 동일 값 복원", () => {
    putCachedFact("t:jpy", "currency", sampleFact());
    const got = getCachedFact("t:jpy", CurrencyInfoSchema);
    expect(got?.value?.krw_per_unit).toBe(9.31);
    expect(got?.confidence).toBe("high");
  });

  it("만료된 캐시는 null", () => {
    putCachedFact("t:expired", "currency", sampleFact());
    // expires_at 을 과거로 강제 주입해 만료 상황 재현
    getDb()
      .$client.prepare("UPDATE fact_cache SET expires_at = ? WHERE key = ?")
      .run("2000-01-01T00:00:00Z", "t:expired");
    expect(getCachedFact("t:expired", CurrencyInfoSchema)).toBeNull();
  });

  it("cachedVerify: 미스 시 produce 실행 + 저장 + 감사 로그", async () => {
    let produced = 0;
    const run = () =>
      cachedVerify({
        key: "t:cv",
        domain: "currency",
        agent: "currency-agent",
        valueSchema: CurrencyInfoSchema,
        produce: async () => {
          produced++;
          return sampleFact();
        },
      });
    const a = await run();
    const b = await run(); // 캐시 히트 → produce 미실행
    expect(a.value?.krw_per_unit).toBe(9.31);
    expect(b.value?.krw_per_unit).toBe(9.31);
    expect(produced).toBe(1);

    const rows = getDb().select().from(auditLog).all();
    expect(rows.some((r) => r.fact_key === "t:cv")).toBe(true);
  });

  it("unverified 도 감사 로그에 남는다", () => {
    appendAudit({
      agent: "poi-agent",
      domain: "poi",
      fact_key: "t:unv",
      fact: unverified<number>("출처 없음"),
    });
    const rows = getDb().select().from(auditLog).all();
    const row = rows.find((r) => r.fact_key === "t:unv");
    expect(row?.confidence).toBe("low");
  });
});
