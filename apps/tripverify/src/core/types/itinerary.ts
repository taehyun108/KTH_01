import type { VerifiedFact } from "./verified-fact";
import type {
  Poi,
  Restaurant,
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
  items: ItineraryItem[];
  total_activity_minutes: number;
  total_travel_minutes: number;
  /** 이동시간 비율 = travel / (activity+travel). */
  travel_ratio: number;
  warnings: string[];
}

export interface VerificationSummary {
  high: number;
  medium: number;
  low: number;
  total: number;
  high_ratio: number;
}

export interface Itinerary {
  query: TripQuery;
  destination_center: { lat: number; lng: number };
  days: ItineraryDay[];
  currency: VerifiedFact<CurrencyInfo> | null;
  weather: VerifiedFact<WeatherDay>[];
  logistics: VerifiedFact<LogisticsInfo> | null;
  flights: VerifiedFact<FlightOption>[];
  verification_summary: VerificationSummary;
  /** 생성 시 전반 경고(데이터 부족 등). */
  notes: string[];
}
