/**
 * 신뢰도 및 출처 등급 정의 (§3, §4).
 *
 * confidence 판정 규칙(§3):
 *   agree_count >= 3 && deviation <= tolerance → "high"   (정상 표기)
 *   agree_count === 2                          → "medium" (⚠ 배지 + 출처 병기)
 *   그 외                                       → "low"    (값 숨김, "확인 필요"만)
 */
export type Confidence = "high" | "medium" | "low";

/**
 * 출처 등급. 불일치 처리 시 다수결이 아니라 등급 우선으로 채택한다(§3).
 *   1 = 공식 (관공서/관광청/항공사 공식/중앙은행)
 *   2 = 플랫폼 API (Google Places / OSM / TripAdvisor 등)
 *   3 = 커뮤니티/블로그 (단독 채택 금지)
 */
export type SourceTier = 1 | 2 | 3;

/** 검증 프로토콜의 Pass 단계 (§3). */
export type VerificationPass = 1 | 2 | 3;

export const CONFIDENCE_BADGE: Record<Confidence, string> = {
  high: "🟢",
  medium: "🟡",
  low: "🔴",
};
