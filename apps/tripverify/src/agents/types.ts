import type { GeoPoint } from "@/core/types/domains";
import type { Observation } from "@/core/verification/observation";

/**
 * 여행 요청 입력. Zod 스키마(schema.ts)로 런타임 검증한다.
 * 다중 도시(destinations)와 구성원(party)을 지원한다.
 */
export interface TripQuery {
  origin: string; // 출발지 (도시/공항 코드)
  country?: string; // 목적지 국가(선택)
  destinations: string[]; // 방문 도시들(순서 = 방문 순서)
  start_date: string; // YYYY-MM-DD
  end_date: string; // YYYY-MM-DD
  party: TravelParty; // 여행 구성원
  budget_krw?: number;
  style: TravelStyle[];
  transport: TransportMode[];
  /** 여행 컨셉/느낌(자유 입력) — 장소 선별에 반영. */
  concept?: string;
}

/** 여행 구성원 구성. */
export interface TravelParty {
  adults: number;
  children: number;
}

export function totalTravelers(p: TravelParty): number {
  return p.adults + p.children;
}

export type TravelStyle = "relax" | "food" | "history" | "activity";
export type TransportMode = "walk" | "transit" | "car";

/**
 * 목적지 지리 컨텍스트. 좌표/통화/시간대 등 하위 에이전트의 공통 입력.
 * 이 값들 자체도 검증 대상이므로 VerifiedFact 로 감싸 파이프라인에서 다룬다.
 */
export interface GeoContext {
  destination: string;
  center: GeoPoint;
  country_code: string; // ISO 3166-1 alpha-2
  currency_code: string; // ISO 4217
  timezone?: string;
}

/**
 * SourceReader — 한 출처에서 관측(Observation)을 읽어오는 주입 가능한 함수.
 * LiveReader(실 HTTP) 와 FixtureReader(테스트/오프라인)가 같은 계약을 구현한다.
 */
export type SourceReader<Args, T> = (
  args: Args,
) => Promise<Observation<T>[]>;

/** 에이전트 실행 결과 공통 형태. */
export interface AgentResult<T> {
  facts: T;
  /** 사용한 출처 도메인(감사용). */
  attempted_sources: string[];
}
