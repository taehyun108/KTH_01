import type { VerifiedFact } from "@/core/types/verified-fact";
import type { Poi, Restaurant } from "@/core/types/domains";
import type { ItineraryDay, ItineraryItem, VerificationSummary } from "@/core/types/itinerary";
import type { TravelLeg } from "@/core/types/domains";
import { hasSourcedValue } from "@/core/types/verified-fact";

// 조립 파라미터(§6)
export const PLAN = {
  DAY_START_MIN: 9 * 60, // 09:00
  POI_DURATION_MIN: 90,
  ALL_DAY_MIN: 360, // 종일 체류형(테마파크) 6시간
  LUNCH_MIN: 12 * 60 + 30, // 12:30
  LUNCH_DURATION: 60,
  DINNER_MIN: 18 * 60 + 30, // 18:30
  DINNER_DURATION: 75,
  MAX_ACTIVITY_MIN: 10 * 60, // 하루 활동 상한 10시간
  TRAVEL_RATIO_CAP: 0.25, // 이동시간 비율 상한 25%
} as const;

export interface DayAssemblyInput {
  date: string;
  weekday: number; // 0=일 … 6=토
  city: string;
  pois: VerifiedFact<Poi>[]; // 방문 순서(최적화 완료)
  legMinutes: number[]; // 각 POI 진입 이동시간(분). [0]=일과 시작→첫 POI
  legMode: TravelLeg["mode"];
  legEstimated: boolean;
  legSource: string;
  lunch?: VerifiedFact<Restaurant>;
  dinner?: VerifiedFact<Restaurant>;
  firstDayStartMin?: number; // 첫날 도착·입국심사 반영 시작시각
  lastDayEndMin?: number; // 마지막날 공항 역산 종료시각
}

/** 분(자정 기준) → "HH:MM". */
export function toHHMM(min: number): string {
  const h = Math.floor(min / 60) % 24;
  const m = min % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

/** 구조화된 영업시간(7요일 배열)에서 [s,e] 창을 수용하는지. 정보 없으면 제약 없음. */
export function fitsOpeningHours(poi: Poi, weekday: number, startMin: number, endMin: number): boolean {
  if (poi.closed_days?.includes(weekday)) return false;
  const oh = poi.opening_hours;
  if (!oh || oh.length !== 7) return true; // 시간 정보 미확인 → 배치 허용(추정 금지)
  const win = oh[weekday];
  if (win === null || win === undefined) return false; // 해당 요일 휴무
  const m = /^(\d{2}):(\d{2})-(\d{2}):(\d{2})$/.exec(win);
  if (!m) return true;
  const openMin = Number(m[1]) * 60 + Number(m[2]);
  const closeMin = Number(m[3]) * 60 + Number(m[4]);
  return startMin >= openMin && endMin <= closeMin;
}

/**
 * 하루 일정을 조립한다. 휴무/영업시간 밖 POI 는 배치하지 않고 경고로 남긴다
 * (→ 휴무일 방문 배치 0건, §10). 활동 10시간·이동 25% 상한을 검사한다.
 */
export function assembleDay(input: DayAssemblyInput): ItineraryDay {
  const warnings: string[] = [];
  const items: ItineraryItem[] = [];
  let cursor = input.firstDayStartMin ?? PLAN.DAY_START_MIN;
  const endCap = input.lastDayEndMin ?? 24 * 60;
  let activity = 0;
  let travel = 0;
  let lunchPlaced = false;
  let dinnerPlaced = false;

  const placeMeal = (meal: VerifiedFact<Restaurant> | undefined, at: number, dur: number, label: string): void => {
    if (!meal || !hasSourcedValue(meal)) return;
    items.push({
      kind: "food",
      name: meal.value.name,
      place: meal,
      start: toHHMM(at),
      end: toHHMM(at + dur),
    });
    activity += dur;
  };

  for (let i = 0; i < input.pois.length; i++) {
    const fact = input.pois[i]!;
    if (!hasSourcedValue(fact)) {
      // 값·출처가 전혀 없는 완전 미확인 항목만 제외(유령 장소 0건 유지)
      warnings.push(`출처 없는 항목 제외: ${fact.value?.name ?? "미상"}`);
      continue;
    }
    const poi = fact.value;
    const leg = input.legMinutes[i] ?? 0;

    // 식사 시간대 진입 시 식당 삽입
    if (!lunchPlaced && cursor + leg >= PLAN.LUNCH_MIN) {
      placeMeal(input.lunch, Math.max(cursor + leg, PLAN.LUNCH_MIN), PLAN.LUNCH_DURATION, "점심");
      lunchPlaced = true;
      if (input.lunch && hasSourcedValue(input.lunch)) cursor = Math.max(cursor + leg, PLAN.LUNCH_MIN) + PLAN.LUNCH_DURATION;
    }

    // 종일 체류형(테마파크)은 긴 블록으로 배치
    const durationMin = poi.all_day ? PLAN.ALL_DAY_MIN : PLAN.POI_DURATION_MIN;
    const startMin = cursor + leg;
    const endMin = startMin + durationMin;

    if (!fitsOpeningHours(poi, input.weekday, startMin, endMin)) {
      warnings.push(`휴무/영업시간 밖으로 제외: ${poi.name}`);
      continue; // 휴무일·시간 밖은 배치하지 않음
    }
    if (activity + durationMin > PLAN.MAX_ACTIVITY_MIN && items.some((it) => it.kind === "poi")) {
      warnings.push("하루 활동 10시간 상한 초과 → 이후 일정 다음 날 재배치 권장");
      break;
    }
    if (endMin > endCap) {
      warnings.push("공항 역산 시각 초과 → 마지막 일정 제외");
      break;
    }
    if (poi.all_day) {
      warnings.push(`${poi.name}: 종일 코스 — 내부 어트랙션·식당 이용(순서·메뉴는 후기 링크 참고)`);
    }

    items.push({
      kind: "poi",
      name: poi.name,
      place: fact,
      start: toHHMM(startMin),
      end: toHHMM(endMin),
      travel_from_prev: {
        minutes: leg,
        mode: input.legMode,
        estimated: input.legEstimated,
        source_name: input.legSource,
      },
    });
    travel += leg;
    activity += durationMin;
    cursor = endMin;
  }

  // 저녁 삽입
  if (!dinnerPlaced) {
    placeMeal(input.dinner, Math.max(cursor, PLAN.DINNER_MIN), PLAN.DINNER_DURATION, "저녁");
    dinnerPlaced = true;
  }

  const denom = activity + travel;
  const travel_ratio = denom > 0 ? travel / denom : 0;
  if (travel_ratio > PLAN.TRAVEL_RATIO_CAP) {
    warnings.push(`이동시간 비율 ${(travel_ratio * 100).toFixed(0)}% > 25% → 동선 재배치 권장`);
  }

  return {
    date: input.date,
    weekday: input.weekday,
    city: input.city,
    items,
    total_activity_minutes: activity,
    total_travel_minutes: travel,
    travel_ratio,
    warnings,
  };
}

/** 검증 등급 분포 요약(§8 검증 리포트). */
export function summarize(facts: VerifiedFact<unknown>[]): VerificationSummary {
  let high = 0;
  let medium = 0;
  let low = 0;
  for (const f of facts) {
    if (f.confidence === "high") high++;
    else if (f.confidence === "medium") medium++;
    else low++;
  }
  const total = facts.length;
  return { high, medium, low, total, high_ratio: total > 0 ? high / total : 0 };
}
