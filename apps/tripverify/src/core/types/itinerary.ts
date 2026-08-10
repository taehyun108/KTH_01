import type { VerifiedFact } from "./verified-fact";
import type {
  Poi,
  Restaurant,
  Hotel,
  WeatherDay,
  CurrencyInfo,
  FlightOption,
  LogisticsInfo,
  TravelLeg,
} from "./domains";
import type { TripQuery } from "@/agents/types";

/** 일정 한 항목(관광/식사/이동). place 는 검증된 FACT 를 그대로 보존한다. */
export interface ItineraryItem {
  kind: "poi" | "food";
  name: string;
  place: VerifiedFact<Poi> | VerifiedFact<Restaurant>;
  start: string; // HH:MM (현지)
  end: string; // HH:MM
  /** 직전 항목에서 이동 정보(첫 항목은 없음). */
  travel_from_prev?: {
    minutes: number;
    mode: TravelLeg["mode"];
    estimated: boolean;
    source_name: string;
  };
}

export interface ItineraryDay {
  date: string; // YYYY-MM-DD
  weekday: number; // 0=일 … 6=토
  city: string; // 이 날 머무는 도시
  items: ItineraryItem[];
  total_activity_minutes: number;
  total_travel_minutes: number;
  /** 이동시간 비율 = travel / (activity+travel). */
  travel_ratio: number;
  warnings: string[];
}

/** 도시 간 이동방법(§ 이동방법). 좌표 기반 추정이므로 신뢰도를 명시한다. */
export interface CityTransfer {
  from_city: string;
  to_city: string;
  distance_km: number;
  suggested_mode: "train" | "car" | "flight";
  fact: VerifiedFact<{ distance_km: number; duration_minutes: number; mode: string }>;
}

/** 예산 항목(카테고리별). 금액은 검증 래퍼로 감싸 신뢰도/출처를 보존한다. */
export type BudgetCategory =
  | "flight"
  | "intercity"
  | "lodging"
  | "food"
  | "admission"
  | "local_transport";

export interface BudgetLine {
  category: BudgetCategory;
  label: string;
  /** KRW 총액. 검증된 값(입장료 등)은 medium+, 계획 가정은 low(추정). */
  amount_krw: VerifiedFact<number>;
}

export interface BudgetEstimate {
  currency: VerifiedFact<CurrencyInfo> | null;
  lines: BudgetLine[];
  total_krw: number; // 추정 포함 합계
  verified_krw: number; // 검증(medium 이상) 항목만의 합계
  per_person_krw: number;
  note: string;
  /** 사용자 예산(있으면). */
  budget_krw?: number;
  /** 비용 구성 등급: standard(기본) / budget(최소비용). */
  tier: "standard" | "budget";
  /** 예산 초과 여부. */
  over_budget: boolean;
  /** 초과액(원). 초과 아니면 0. */
  shortfall_krw: number;
  /** 국내여행(원화 기준, 환전 불필요). */
  domestic: boolean;
}

export interface VerificationSummary {
  high: number;
  medium: number;
  low: number;
  total: number;
  high_ratio: number;
}

/** 도시별 추천 숙소(OSM 실존 호텔). 동선 근처·품질 순으로 정렬된 실제 후보들. */
export interface CityLodging {
  city: string;
  options: VerifiedFact<Hotel>[];
}

export interface Itinerary {
  query: TripQuery;
  destination_center: { lat: number; lng: number };
  cities: { name: string; center: { lat: number; lng: number } }[];
  days: ItineraryDay[];
  /** 도시별 추천 숙소(실존 OSM 호텔). */
  lodging: CityLodging[];
  transfers: CityTransfer[];
  budget: BudgetEstimate;
  currency: VerifiedFact<CurrencyInfo> | null;
  weather: VerifiedFact<WeatherDay>[];
  logistics: VerifiedFact<LogisticsInfo> | null;
  flights: VerifiedFact<FlightOption>[];
  verification_summary: VerificationSummary;
  /** 생성 시 전반 경고(데이터 부족 등). */
  notes: string[];
}
