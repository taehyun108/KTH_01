/**
 * 인메모리 슬라이딩 윈도우 레이트리밋 (§8 레이트리밋).
 * 단일 인스턴스 개발/운영용. 다중 인스턴스에서는 Redis 등으로 교체.
 */
interface Bucket {
  hits: number[];
}
const store = new Map<string, Bucket>();

export interface RateResult {
  ok: boolean;
  remaining: number;
  retryAfterSec: number;
}

export function rateLimit(
  key: string,
  limit = 20,
  windowMs = 60_000,
  now: number = Date.now(),
): RateResult {
  const bucket = store.get(key) ?? { hits: [] };
  bucket.hits = bucket.hits.filter((t) => now - t < windowMs);
  if (bucket.hits.length >= limit) {
    const oldest = bucket.hits[0]!;
    store.set(key, bucket);
    return {
      ok: false,
      remaining: 0,
      retryAfterSec: Math.max(1, Math.ceil((windowMs - (now - oldest)) / 1000)),
    };
  }
  bucket.hits.push(now);
  store.set(key, bucket);
  return { ok: true, remaining: limit - bucket.hits.length, retryAfterSec: 0 };
}

/** 요청에서 클라이언트 식별 키 추출 (프록시 헤더 우선). */
export function clientKey(req: Request): string {
  const xff = req.headers.get("x-forwarded-for");
  if (xff) return xff.split(",")[0]!.trim();
  return req.headers.get("x-real-ip") ?? "anonymous";
}

/** 테스트용 초기화. */
export function __resetRateLimit(): void {
  store.clear();
}
