import type { Source } from "../types/verified-fact";
import type { SourceTier } from "../types/confidence";

/**
 * 출처 등급 우선순위 (§3).
 * 불일치 처리 시 다수결이 아니라 등급 우선으로 채택한다.
 *   공식(1) > 정부·관광청(1) > 대형 플랫폼 API(2) > 블로그·커뮤니티(3, 단독 채택 금지)
 * tier 숫자가 낮을수록 우선.
 */
export function rankByTier<T extends { source?: Source; tier?: SourceTier }>(
  candidates: T[],
): T[] {
  return [...candidates].sort((a, b) => tierOf(a) - tierOf(b));
}

function tierOf(c: { source?: Source; tier?: SourceTier }): SourceTier {
  return (c.tier ?? c.source?.tier ?? 3) as SourceTier;
}

/** 커뮤니티(tier 3) 단독 출처는 채택 불가(§3). */
export function isSoleCommunitySource(sources: Source[]): boolean {
  return sources.length > 0 && sources.every((s) => s.tier === 3);
}

/** 서로 다른 운영사/도메인인지 — Pass 1·2 독립성 판정 보조(§3). */
export function isIndependentDomain(a: Source, b: Source): boolean {
  return registrableHost(a.url) !== registrableHost(b.url);
}

function registrableHost(url: string): string {
  try {
    const host = new URL(url).hostname.toLowerCase();
    const parts = host.split(".");
    return parts.slice(-2).join(".");
  } catch {
    return url;
  }
}
