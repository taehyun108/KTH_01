/**
 * 도메인 값 타입 (§2 서브에이전트 산출물의 개별 FACT 값 형태).
 * 이 타입들은 VerifiedFact<T> 의 T 로 감싸져 사용된다.
 * Phase 0 은 스키마·검증 기반이 되는 최소 형태만 정의한다.
 */

// --- 공통 ---
export interface GeoPoint {
  lat: number;
  lng: number;
}

// --- currency-agent → currency.json ---
export interface CurrencyInfo {
  /** ISO 4217 통화 코드 (예: "JPY"). */
  code: string;
  /** 1 단위당 KRW 환율. */
  krw_per_unit: number;
  base: "KRW";
  /** 카드/현금 관행 요약. */
  card_practice?: string;
  tipping_practice?: string;
}

// --- weather-agent → weather.json ---
export interface WeatherDay {
  date: string; // YYYY-MM-DD
  temp_min_c: number;
  temp_max_c: number;
  precipitation_probability?: number; // 0~100
  /** 예보(forecast) vs 기후평년값(climatology). */
  kind: "forecast" | "climatology";
}

// --- poi-agent → pois.json ---
export interface Poi {
  name: string;
  location: GeoPoint;
  /** 요일별 운영시간 [0=일 … 6=토], "HH:MM-HH:MM" 또는 null(휴무). */
  opening_hours?: (string | null)[];
  closed_days?: number[];
  admission_fee_local?: number | null;
  reservation_required?: boolean;
}

// --- food-agent → restaurants.json ---
export interface Restaurant {
  name: string;
  location: GeoPoint;
  opening_hours?: (string | null)[];
  closed_days?: number[];
  /** 1~4 (저렴~고가). */
  price_level?: 1 | 2 | 3 | 4;
  reservation_required?: boolean;
}

// --- flight-agent → flights.json ---
export interface FlightOption {
  flight_no: string;
  depart_local: string; // ISO8601 현지시간
  arrive_local: string; // ISO8601 현지시간
  stops: number;
  duration_minutes: number;
  price_estimate_krw?: number; // "조회 시점 기준" 라벨 필수
}

// --- route-agent → routes.json ---
export interface TravelLeg {
  from: GeoPoint;
  to: GeoPoint;
  mode: "walk" | "transit" | "car";
  minutes: number; // 실제 소요시간(직선거리 금지)
}

// --- logistics-agent → logistics.json ---
export interface LogisticsInfo {
  visa_required?: boolean;
  entry_requirements?: string;
  power_plug?: string; // 예: "Type A/B, 100V"
  esim_note?: string;
  public_holidays?: string[]; // YYYY-MM-DD
}
