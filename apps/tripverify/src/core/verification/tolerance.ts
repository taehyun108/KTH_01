/**
 * 허용 오차 상수 (§3). 검증 프로토콜(Phase 1)이 편차 판정에 사용한다.
 * 값은 여기에 단일 정의하고, 코드 전반에서 매직넘버로 흩뿌리지 않는다.
 */
export const TOLERANCE = {
  /** 환율: ±0.5% */
  fx_rate_ratio: 0.005,
  /** 좌표: 100m 이내 (하버사인 거리, meter) */
  geo_distance_m: 100,
  /** 항공 가격: ±15% ("조회 시점 기준" 라벨 필수) */
  flight_price_ratio: 0.15,
  /** 입장료: ±10% */
  admission_fee_ratio: 0.1,
} as const;

/** 영업시간은 완전 일치. 불일치 시 medium 강등(§3). */
export const OPENING_HOURS_EXACT_MATCH = true;

/**
 * Pass 3(시간차 재조회) 최소 간격. 변동 데이터를 최소 60초 이상 간격을 두고
 * 재조회해 동일 값(허용오차 내)인지 확인한다(§3).
 */
export const PASS3_MIN_INTERVAL_MS = 60_000;
