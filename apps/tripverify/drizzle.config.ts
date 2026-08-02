import { defineConfig } from "drizzle-kit";

/** 개발은 SQLite(better-sqlite3), 운영은 Postgres 로 이관 예정.
 *  DB 경로는 env 로 주입하고 코드에 하드코딩하지 않는다. */
export default defineConfig({
  dialect: "sqlite",
  schema: "./src/db/schema.ts",
  out: "./src/db/migrations",
  dbCredentials: {
    url: process.env.DATABASE_URL ?? "./tripverify.dev.sqlite",
  },
});
