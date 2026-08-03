import { NextResponse } from "next/server";
import { sql } from "drizzle-orm";
import { getDb } from "@/db/client";
import { verified, unverified } from "@/core/factory/make-fact";
import { isRenderable } from "@/core/types/verified-fact";
import { VerifiedFactSchema } from "@/core/schema/verified-fact.schema";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Phase 0 헬스체크: (1) DB 연결/스키마 부트스트랩, (2) VerifiedFact 불변식 self-check.
 * 스키마가 잘못된 FACT 를 실제로 거부하는지까지 확인해 200 을 반환한다.
 */
export function GET() {
  const checks: Record<string, boolean> = {};
  // DB 는 선택적(캐시/감사용). 서버리스 읽기전용 FS 에서는 비활성화될 수 있으며
  // 이는 실패가 아니다 → ok 판정에서 제외하고 정보성으로만 보고한다.
  const info: Record<string, boolean> = {};

  // 1) DB 연결 + 테이블 존재 확인 (정보성)
  try {
    const db = getDb();
    if (db) {
      db.run(sql`SELECT 1`);
      const tables = db.all<{ name: string }>(sql`
        SELECT name FROM sqlite_master
        WHERE type='table' AND name IN ('audit_log','fact_cache')
      `);
      info.db_connected = true;
      info.tables_ready = tables.length === 2;
    } else {
      info.db_connected = false;
      info.tables_ready = false;
    }
  } catch {
    info.db_connected = false;
    info.tables_ready = false;
  }

  // 2) 팩토리로 정상 FACT 생성 (환율 예시)
  try {
    const fx = verified<number>({
      value: 9.31,
      confidence: "high",
      sources: [
        {
          name: "ECB",
          url: "https://www.ecb.europa.eu/",
          tier: 1,
          retrieved_at: new Date().toISOString(),
        },
        {
          name: "exchangerate.host",
          url: "https://exchangerate.host/",
          tier: 2,
          retrieved_at: new Date().toISOString(),
        },
        {
          name: "한국수출입은행",
          url: "https://www.koreaexim.go.kr/",
          tier: 1,
          retrieved_at: new Date().toISOString(),
        },
      ],
      verification: {
        passes_completed: 3,
        agree_count: 3,
        deviation: 0.001,
        checked_at: new Date().toISOString(),
      },
    });
    checks.factory_verified_ok = isRenderable(fx);
    checks.factory_unverified_ok =
      unverified<number>("출처 3곳 미확보").confidence === "low";
  } catch {
    checks.factory_verified_ok = false;
    checks.factory_unverified_ok = false;
  }

  // 3) 스키마가 '출처 없는 값'을 실제로 거부하는지 (음성 테스트)
  const bad = VerifiedFactSchema.safeParse({
    value: 100,
    confidence: "high",
    sources: [], // 출처 없음 → 반드시 실패해야 함
    verification: {
      passes_completed: 1,
      agree_count: 0,
      checked_at: new Date().toISOString(),
    },
  });
  checks.schema_rejects_sourceless = !bad.success;

  // 핵심 정합성(팩토리·스키마)만 ok 판정. DB 는 info 로 분리.
  const ok = Object.values(checks).every(Boolean);
  return NextResponse.json(
    { ok, phase: 0, checks, db: info, checked_at: new Date().toISOString() },
    { status: ok ? 200 : 503 },
  );
}
