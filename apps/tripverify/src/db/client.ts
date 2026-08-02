import "server-only";
import Database from "better-sqlite3";
import { drizzle } from "drizzle-orm/better-sqlite3";
import { sql } from "drizzle-orm";
import * as schema from "./schema";

/**
 * 개발용 SQLite 클라이언트. 운영에서는 Postgres 드라이버로 교체(§7).
 * DB 경로는 env 로 주입하며 코드에 하드코딩하지 않는다(§5).
 *
 * Phase 0 은 마이그레이션 파일 없이도 헬스체크가 돌도록 스키마를
 * 부트스트랩(ensureSchema)한다. Phase 1+ 에서 drizzle-kit 마이그레이션으로 대체.
 */

const DB_PATH = process.env.DATABASE_URL ?? "./tripverify.dev.sqlite";

let _db: ReturnType<typeof drizzle<typeof schema>> | null = null;

export function getDb() {
  if (_db) return _db;
  const sqlite = new Database(DB_PATH);
  sqlite.pragma("journal_mode = WAL");
  _db = drizzle(sqlite, { schema });
  ensureSchema(_db);
  return _db;
}

function ensureSchema(db: ReturnType<typeof drizzle<typeof schema>>): void {
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
