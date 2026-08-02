/** 도메인별 캐시 TTL (§7). 변동성이 큰 도메인일수록 짧게. */
export const CACHE_TTL_MS = {
  currency: 10 * 60_000, // 10분
  weather: 3 * 60 * 60_000, // 3시간
  poi: 7 * 24 * 60 * 60_000, // 7일
  food: 7 * 24 * 60 * 60_000, // 7일
  flight: 30 * 60_000, // 30분
  route: 24 * 60 * 60_000, // 1일
  logistics: 24 * 60 * 60_000, // 1일
} as const;

export type CacheDomain = keyof typeof CACHE_TTL_MS;
