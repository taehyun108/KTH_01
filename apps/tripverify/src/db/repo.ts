import "server-only";
import { eq } from "drizzle-orm";
import type { z } from "zod";
import { getDb } from "./client";
import { auditLog, factCache } from "./schema";
import type { VerifiedFact } from "@/core/types/verified-fact";
import { reviveFact } from "@/core/factory/make-fact";
import { CACHE_TTL_MS, type CacheDomain } from "@/lib/cache-ttl";

/**
 * 검증 결과 캐시 + 감사 로그 저장소 (§7, §10).
 * 캐시는 도메인별 TTL 로 만료를 관리하고, 모든 판정은 audit_log 에 남긴다.
 */

/** 캐시 조회. 만료됐거나 없으면 null. 값 스키마로 재검증하며 복원한다. */
export function getCachedFact<S extends z.ZodTypeAny>(
  key: string,
  valueSchema: S,
): VerifiedFact<z.infer<S>> | null {
  const db = getDb();
  const row = db.select().from(factCache).where(eq(factCache.key, key)).get();
  if (!row) return null;
  if (row.expires_at && Date.parse(row.expires_at) < Date.now()) return null;
  try {
    return reviveFact(valueSchema, JSON.parse(row.value_json));
  } catch {
    return null; // 손상된 캐시는 무시
  }
}

/** 캐시 저장. 도메인 TTL 로 expires_at 계산. */
export function putCachedFact<T>(
  key: string,
  domain: CacheDomain,
  fact: VerifiedFact<T>,
): void {
  const db = getDb();
  const expires_at = new Date(Date.now() + CACHE_TTL_MS[domain]).toISOString();
  const value_json = JSON.stringify(fact);
  db.insert(factCache)
    .values({ key, domain, confidence: fact.confidence, value_json, expires_at })
    .onConflictDoUpdate({
      target: factCache.key,
      set: { confidence: fact.confidence, value_json, expires_at, domain },
    })
    .run();
}

/** 검증 판정 1건을 감사 로그에 기록(§10 사후 추적). */
export function appendAudit<T>(params: {
  agent: string;
  domain: string;
  fact_key: string;
  fact: VerifiedFact<T>;
}): void {
  const db = getDb();
  const { agent, domain, fact_key, fact } = params;
  db.insert(auditLog)
    .values({
      agent,
      domain,
      fact_key,
      confidence: fact.confidence,
      agree_count: fact.verification.agree_count,
      passes_completed: fact.verification.passes_completed,
      deviation: fact.verification.deviation ?? null,
      sources_json: JSON.stringify(fact.sources),
      payload_json: JSON.stringify(fact),
    })
    .run();
}

/**
 * 캐시 우선 조회 → 미스 시 producer 실행 → 저장 + 감사. 파이프라인 공통 헬퍼.
 */
export async function cachedVerify<S extends z.ZodTypeAny>(params: {
  key: string;
  domain: CacheDomain;
  agent: string;
  valueSchema: S;
  produce: () => Promise<VerifiedFact<z.infer<S>>>;
}): Promise<VerifiedFact<z.infer<S>>> {
  const cached = getCachedFact(params.key, params.valueSchema);
  if (cached) return cached;
  const fact = await params.produce();
  putCachedFact(params.key, params.domain, fact);
  appendAudit({
    agent: params.agent,
    domain: params.domain,
    fact_key: params.key,
    fact,
  });
  return fact;
}
