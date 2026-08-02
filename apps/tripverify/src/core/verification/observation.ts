import type { Source } from "../types/verified-fact";
import type { GeoPoint } from "../types/domains";
import { haversineMeters } from "@/lib/geo";

/**
 * Observation — 한 출처가 특정 Pass 에서 읽은 단일 raw 값 (§3).
 * verifier 는 여러 Observation 을 받아 교차검증한다.
 */
export interface Observation<T> {
  value: T;
  source: Source;
  /** 어느 검증 Pass 의 관측인가 (1=1차, 2=독립2차, 3=시간차 재조회). */
  pass: 1 | 2 | 3;
}

/**
 * Comparator — 두 값이 "동의(agree)"하는지, 그리고 편차가 얼마인지 정의.
 * 도메인별 허용오차(§3)를 이 안에 캡슐화한다.
 */
export interface Comparator<T> {
  agree(a: T, b: T): boolean;
  /** 채택값 대비 상대 편차(리포트/판정용). 비수치형은 0. */
  deviation(adopted: T, other: T): number;
}

/** 수치 상대오차 비교자 (환율 ±0.5%, 항공가 ±15%, 입장료 ±10% 등). */
export function numericRatio(tolerance: number): Comparator<number> {
  return {
    agree: (a, b) => relDiff(a, b) <= tolerance,
    deviation: (adopted, other) => relDiff(adopted, other),
  };
}

/** 좌표 거리 비교자 (100m 이내). */
export function geoWithin(maxMeters: number): Comparator<GeoPoint> {
  return {
    agree: (a, b) => haversineMeters(a, b) <= maxMeters,
    deviation: (adopted, other) => haversineMeters(adopted, other),
  };
}

/** 완전 일치 비교자 (영업시간·문자열·불리언). 불일치 시 편차 1. */
export function exact<T>(): Comparator<T> {
  return {
    agree: (a, b) => stableEqual(a, b),
    deviation: (adopted, other) => (stableEqual(adopted, other) ? 0 : 1),
  };
}

function relDiff(a: number, b: number): number {
  const denom = Math.max(Math.abs(a), Math.abs(b), 1e-9);
  return Math.abs(a - b) / denom;
}

function stableEqual(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}
