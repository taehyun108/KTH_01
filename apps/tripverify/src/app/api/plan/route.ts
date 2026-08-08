import { NextResponse } from "next/server";
import { TripQuerySchema } from "@/agents/schema";
import { runPipeline } from "@/pipeline/run";
import { liveDeps } from "@/pipeline/live-deps";
import { rateLimit, clientKey } from "@/lib/rate-limit";
import type { TripQuery } from "@/agents/types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
// 외부 무료 API 다중 호출을 고려한 함수 최대 실행시간(Vercel Hobby 상한 60초).
export const maxDuration = 60;

const MAX_BODY_BYTES = 8_192;

/**
 * POST /api/plan — 여행 요청을 받아 검증된 일정을 생성한다.
 * 입력은 Zod 로 검증하고, 파이프라인은 검증 통과 데이터만으로 일정을 조립한다.
 * 레이트리밋(분당 20회) + 본문 크기 제한 적용(§8).
 */
export async function POST(req: Request) {
  const rl = rateLimit(clientKey(req));
  if (!rl.ok) {
    return NextResponse.json(
      { error: "rate limited", retry_after_sec: rl.retryAfterSec },
      { status: 429, headers: { "retry-after": String(rl.retryAfterSec) } },
    );
  }

  const raw = await req.text();
  if (raw.length > MAX_BODY_BYTES) {
    return NextResponse.json({ error: "body too large" }, { status: 413 });
  }

  let body: unknown;
  try {
    body = JSON.parse(raw);
  } catch {
    return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
  }

  const parsed = TripQuerySchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json(
      { error: "invalid TripQuery", issues: parsed.error.issues },
      { status: 422 },
    );
  }

  try {
    // 서버리스 하드 리밋(60s) 전에 반드시 응답하도록 52s 가드.
    const guard = new Promise<null>((resolve) => setTimeout(() => resolve(null), 52_000));
    const itinerary = await Promise.race([
      runPipeline(parsed.data as TripQuery, liveDeps()),
      guard,
    ]);
    if (!itinerary) {
      return NextResponse.json(
        { error: "생성 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.", timeout: true },
        { status: 504 },
      );
    }
    return NextResponse.json(itinerary, { status: 200 });
  } catch (e) {
    return NextResponse.json(
      { error: "pipeline failed", detail: e instanceof Error ? e.message : String(e) },
      { status: 500 },
    );
  }
}
