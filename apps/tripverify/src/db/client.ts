import "server-only";
import { drizzle } from "drizzle-orm/better-sqlite3";
import { sql } from "drizzle-orm";
import { createRequire } from "node:module";
import * as schema from "./schema";

/**
 * 개발용 SQLite 클라이언트. 운영에서는 Postgres 드라이버로 교체(§7).
 * DB 경로는 env 로 주입하며 코드에 하드코딩하지 않는다(§5).
 *
 * 서버리스(Vercel 등) 대응: DB 는 '선택적'이다. 읽기전용 FS 이거나 네이티브
 * 바이너리를 못 실으면 getDb() 가 null 을 반환하고, 캐시/감사만 비활성화될 뿐
 * 앱은 계속 동작한다(§7 캐시는 최적화이지 필수 아님). better-sqlite3 는 로드
 * 실패가 모듈 임포트를 깨지 않도록 lazy require 한다.
 */

const require = createRequire(import.meta.url);

function dbPath(): string {
  if (process.env.DATABASE_URL) return process.env.DATABASE_URL;
  // 서버리스는 /tmp 만 쓰기 가능
  if (process.env.VERCEL || process.env.AWS_LAMBDA_FUNCTION_NAME) {
    return "/tmp/tripverify.sqlite";
  }
  return "./tripverify.dev.sqlite";
}

type Db = ReturnType<typeof drizzle<typeof schema>>;
let _db: Db | null = null;
let _tried = false;

/** DB 핸들. 사용 불가 환경이면 null(호출부는 null 을 견뎌야 한다). */
export function getDb(): Db | null {
  if (_tried) return _db;
  _tried = true;
  try {
    const Database = require("better-sqlite3") as typeof import("better-sqlite3");
    const sqlite = new Database(dbPath());
    sqlite.pragma("journal_mode = WAL");
    _db = drizzle(sqlite, { schema });
    ensureSchema(_db);
  } catch {
    _db = null; // 읽기전용 FS / 네이티브 미탑재 등 → 캐시·감사 비활성화
  }
  return _db;
}

function ensureSchema(db: Db): void {
  db.run(sql`
    CREATE TABLE IF NOT EXISTS audit_log (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
      agent TEXT NOT NULL,
      domain TEXT NOT NULL,
      fact_key TEXT NOT NULL,
      confidence TEXT NOT NULL,
      agree_count INTEGER NOT NULL,
      passes_completed INTEGER NOT NULL,
      deviation REAL,
      sources_json TEXT NOT NULL,
      payload_json TEXT NOT NULL
    )
  `);
  db.run(sql`
    CREATE TABLE IF NOT EXISTS fact_cache (
      key TEXT PRIMARY KEY,
      domain TEXT NOT NULL,
      confidence TEXT NOT NULL,
      value_json TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
      expires_at TEXT
    )
  `);
}

export { schema };
