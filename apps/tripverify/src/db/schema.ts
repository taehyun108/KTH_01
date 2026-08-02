import { sql } from "drizzle-orm";
import { sqliteTable, text, integer, real } from "drizzle-orm/sqlite-core";

/**
 * 감사 로그 (§10: "검증 로그가 DB에 남아 사후 추적 가능").
 * 모든 검증 판정 1건 = 1 행. 사후에 왜 이 confidence 가 나왔는지 재구성 가능.
 */
export const auditLog = sqliteTable("audit_log", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  created_at: text("created_at")
    .notNull()
    .default(sql`(strftime('%Y-%m-%dT%H:%M:%fZ','now'))`),
  /** 어느 서브에이전트 산출인지 (예: "currency-agent"). */
  agent: text("agent").notNull(),
  /** 도메인 (currency/weather/poi/...). */
  domain: text("domain").notNull(),
  /** FACT 식별 키 (예: "osaka:poi:osaka-castle:opening_hours"). */
  fact_key: text("fact_key").notNull(),
  confidence: text("confidence").notNull(), // high|medium|low
  agree_count: integer("agree_count").notNull(),
  passes_completed: integer("passes_completed").notNull(),
  deviation: real("deviation"),
  /** 근거 출처 배열 JSON. */
  sources_json: text("sources_json").notNull(),
  /** 판정 당시 VerifiedFact 전체 스냅샷 JSON. */
  payload_json: text("payload_json").notNull(),
});

/**
 * 검증 결과 캐시 (§7: 캐시 TTL 도메인별 분리).
 * key = 안정적 FACT 식별자, value = VerifiedFact JSON, expires_at 으로 TTL 관리.
 */
export const factCache = sqliteTable("fact_cache", {
  key: text("key").primaryKey(),
  domain: text("domain").notNull(),
  confidence: text("confidence").notNull(),
  /** VerifiedFact 직렬화 JSON. */
  value_json: text("value_json").notNull(),
  created_at: text("created_at")
    .notNull()
    .default(sql`(strftime('%Y-%m-%dT%H:%M:%fZ','now'))`),
  /** TTL 만료 시각 ISO8601. null 이면 무기한. */
  expires_at: text("expires_at"),
});

export type AuditLogRow = typeof auditLog.$inferSelect;
export type FactCacheRow = typeof factCache.$inferSelect;
