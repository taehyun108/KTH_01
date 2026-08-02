import type { TripQuery, GeoContext } from "@/agents/types";
import type { VerifiedFact } from "@/core/types/verified-fact";
import type {
  Poi,
  Restaurant,
  WeatherDay,
  CurrencyInfo,
  FlightOption,
  LogisticsInfo,
} from "@/core/types/domains";
import type { Itinerary, ItineraryDay } from "@/core/types/itinerary";
import type { RoutePlan } from "@/agents/route-agent";
import type { Place } from "@/planner/cluster";
import { isRenderable } from "@/core/types/verified-fact";
import { assembleDay, summarize, type DayAssemblyInput } from "@/planner/assemble";
import { dayCount } from "@/agents/schema";

/**
 * 파이프라인 의존성. 수집 에이전트는 이미 내부에서 verifier 를 거쳐
 * VerifiedFact 를 반환한다. planner(assemble)는 여기서 걸러진 '검증 통과'
 * 데이터만 본다 — 원본 접근 금지(§2).
 */
export interface PipelineDeps {
  resolveContext: (q: TripQuery) => Promise<GeoContext>;
  collectPois: (ctx: GeoContext, q: TripQuery) => Promise<VerifiedFact<Poi>[]>;
  collectFood: (ctx: GeoContext, q: TripQuery) => Promise<VerifiedFact<Restaurant>[]>;
  collectCurrency: (ctx: GeoContext) => Promise<VerifiedFact<CurrencyInfo>>;
  collectWeather: (ctx: GeoContext, q: TripQuery) => Promise<VerifiedFact<WeatherDay>[]>;
  collectFlights: (ctx: GeoContext, q: TripQuery) => Promise<VerifiedFact<FlightOption>[]>;
  collectLogistics: (ctx: GeoContext, q: TripQuery) => Promise<VerifiedFact<LogisticsInfo>>;
  buildRoute: (places: Place[], days: number, mode: TripQuery["transport"][number]) => Promise<RoutePlan>;
}

export async function runPipeline(query: TripQuery, deps: PipelineDeps): Promise<Itinerary> {
  const notes: string[] = [];
  const ctx = await deps.resolveContext(query);
  const nDays = dayCount(query.start_date, query.end_date);

  // 수집 에이전트 병렬 실행 (§9 실행 순서)
  const [pois, food, currency, weather, flights, logistics] = await Promise.all([
    safe(() => deps.collectPois(ctx, query), []),
    safe(() => deps.collectFood(ctx, query), []),
    safe(() => deps.collectCurrency(ctx), null),
    safe(() => deps.collectWeather(ctx, query), []),
    safe(() => deps.collectFlights(ctx, query), []),
    safe(() => deps.collectLogistics(ctx, query), null),
  ]);

  // ⭐ planner 는 검증 통과(high/medium) POI/food 만 본다 (§2, §3 low 숨김)
  const renderablePois = pois.filter(isRenderable);
  const renderableFood = food.filter(isRenderable);
  if (renderablePois.length === 0) {
    notes.push(
      "검증을 통과한 관광지가 없어 일정을 생성할 수 없습니다. (외부 출처 조회 불가 또는 교차검증 실패)",
    );
  }

  const places: Place[] = renderablePois.map((f, i) => ({
    id: `poi-${i}`,
    location: f.value.location,
  }));
  const primaryMode = query.transport[0] ?? "transit";
  const route = places.length > 0
    ? await deps.buildRoute(places, nDays, primaryMode)
    : { days: [], estimated: true, source_name: "" };

  const poiById = new Map(places.map((p, i) => [p.id, renderablePois[i]!] as const));
  const foodQueue = [...renderableFood];

  const days: ItineraryDay[] = [];
  for (let d = 0; d < nDays; d++) {
    const date = addDays(query.start_date, d);
    const weekday = new Date(date + "T00:00:00Z").getUTCDay();
    const dayRoute = route.days[d];
    const orderedPois = (dayRoute?.ordered_place_ids ?? []).map((id) => poiById.get(id)!).filter(Boolean);
    const legMinutes = (dayRoute?.leg_seconds ?? orderedPois.map(() => 0)).map((s) => Math.round(s / 60));

    const input: DayAssemblyInput = {
      date,
      weekday,
      pois: orderedPois,
      legMinutes,
      legMode: primaryMode,
      legEstimated: route.estimated,
      legSource: route.source_name || "n/a",
      ...(foodQueue.length > 0 ? { lunch: foodQueue.shift()! } : {}),
      ...(foodQueue.length > 0 ? { dinner: foodQueue.shift()! } : {}),
      ...firstLastDayBounds(d, nDays, flights),
    };
    days.push(assembleDay(input));
  }

  const allFacts: VerifiedFact<unknown>[] = [
    ...pois,
    ...food,
    ...weather,
    ...flights,
    ...(currency ? [currency] : []),
    ...(logistics ? [logistics] : []),
  ];

  return {
    query,
    destination_center: ctx.center,
    days,
    currency,
    weather,
    logistics,
    flights,
    verification_summary: summarize(allFacts),
    notes,
  };
}

/** 첫날/마지막날 공항 경계 반영(§6). 항공 검증값이 있을 때만 적용. */
function firstLastDayBounds(
  d: number,
  nDays: number,
  flights: VerifiedFact<FlightOption>[],
): { firstDayStartMin?: number; lastDayEndMin?: number } {
  const arr = flights.find(isRenderable);
  if (d === 0 && arr) {
    const arriveMin = localMinutes(arr.value.arrive_local);
    // 입국심사 90분 + 공항→숙소 60분
    return { firstDayStartMin: Math.min(arriveMin + 150, 20 * 60) };
  }
  if (d === nDays - 1 && arr) {
    const departMin = localMinutes(arr.value.depart_local);
    // 출국 3시간 전 공항 도착 → 그 이전까지 일정
    return { lastDayEndMin: Math.max(departMin - 180 - 60, 9 * 60) };
  }
  return {};
}

function localMinutes(iso: string): number {
  const m = /T(\d{2}):(\d{2})/.exec(iso);
  return m ? Number(m[1]) * 60 + Number(m[2]) : 12 * 60;
}

function addDays(date: string, d: number): string {
  return new Date(Date.parse(date) + d * 86_400_000).toISOString().slice(0, 10);
}

async function safe<T>(fn: () => Promise<T>, fallback: T): Promise<T> {
  try {
    return await fn();
  } catch {
    return fallback;
  }
}
