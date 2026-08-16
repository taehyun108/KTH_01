import type { TripQuery, GeoContext } from "@/agents/types";
import type { VerifiedFact } from "@/core/types/verified-fact";
import type {
  Poi,
  Restaurant,
  Hotel,
  WeatherDay,
  CurrencyInfo,
  FlightOption,
  LogisticsInfo,
} from "@/core/types/domains";
import type { Itinerary, ItineraryDay, CityLodging } from "@/core/types/itinerary";
import type { RoutePlan, DayRoute } from "@/agents/route-agent";
import type { Place } from "@/planner/cluster";
import type { GeoPoint } from "@/core/types/domains";
import { hasSourcedValue } from "@/core/types/verified-fact";
import { haversineMeters } from "@/lib/geo";
import { assembleDay, summarize, type DayAssemblyInput } from "@/planner/assemble";
import { estimateBudget } from "@/planner/budget";
import { planTransfers, type CityNode } from "@/agents/transfer-agent";
import { dayCount, allocateNights } from "@/agents/schema";

/**
 * 파이프라인 의존성. 수집 에이전트는 내부에서 verifier 를 거쳐 VerifiedFact 를
 * 반환한다. planner(assemble)/budget 은 여기서 걸러진 '검증 통과' 데이터만 본다(§2).
 * resolveContext 는 도시명 단위로 호출된다(다중 도시).
 */
export interface PipelineDeps {
  resolveContext: (city: string, q: TripQuery) => Promise<GeoContext>;
  collectPois: (ctx: GeoContext, q: TripQuery) => Promise<VerifiedFact<Poi>[]>;
  collectFood: (ctx: GeoContext, q: TripQuery) => Promise<VerifiedFact<Restaurant>[]>;
  collectHotels: (ctx: GeoContext, q: TripQuery) => Promise<VerifiedFact<Hotel>[]>;
  collectCurrency: (ctx: GeoContext) => Promise<VerifiedFact<CurrencyInfo>>;
  collectWeather: (ctx: GeoContext, startDate: string, endDate: string) => Promise<VerifiedFact<WeatherDay>[]>;
  collectFlights: (ctx: GeoContext, q: TripQuery) => Promise<VerifiedFact<FlightOption>[]>;
  collectLogistics: (ctx: GeoContext, q: TripQuery) => Promise<VerifiedFact<LogisticsInfo>>;
  buildRoute: (places: Place[], days: number, mode: TripQuery["transport"][number]) => Promise<RoutePlan>;
}

interface CityBundle {
  city: string;
  ctx: GeoContext | null;
  days: ItineraryDay[];
  pois: VerifiedFact<Poi>[];
  food: VerifiedFact<Restaurant>[];
  hotels: VerifiedFact<Hotel>[];
  weather: VerifiedFact<WeatherDay>[];
}

export async function runPipeline(query: TripQuery, deps: PipelineDeps): Promise<Itinerary> {
  const notes: string[] = [];
  const nDays = dayCount(query.start_date, query.end_date);
  const cityNames = query.destinations;
  const alloc = allocateNights(nDays, cityNames.length); // 도시별 일수
  const primaryMode = query.transport[0] ?? "transit";

  // 도시별 시작 인덱스(전역 날짜 오프셋)
  const startIndex: number[] = [];
  alloc.reduce((acc, n, i) => ((startIndex[i] = acc), acc + n), 0);

  // 도시별 병렬 처리
  const bundles = await Promise.all(
    cityNames.map((city, ci) => buildCity(query, deps, city, startIndex[ci]!, alloc[ci]!, primaryMode)),
  );

  const resolved = bundles.filter((b) => b.ctx !== null);
  if (resolved.length === 0) {
    return emptyItinerary(
      query,
      nDays,
      cityNames,
      "목적지 컨텍스트(좌표/통화)를 조회하지 못해 일정을 생성할 수 없습니다. (이 환경은 외부 API 접근이 차단되어 있습니다)",
    );
  }

  const firstCtx = resolved[0]!.ctx!;

  // 국가 단위 정보(통화/입국정보) + 출발지 항공: 한 번만
  const [currency, logistics, flights] = await Promise.all([
    safe(() => deps.collectCurrency(firstCtx), null, 12_000),
    safe(() => deps.collectLogistics(firstCtx, query), null, 12_000),
    safe(() => deps.collectFlights(firstCtx, query), [] as VerifiedFact<FlightOption>[], 12_000),
  ]);

  const days = bundles.flatMap((b) => b.days);
  const allPois = bundles.flatMap((b) => b.pois);
  const allFood = bundles.flatMap((b) => b.food);
  const weather = bundles.flatMap((b) => b.weather);

  // 도시별 추천 숙소: 동선(관광지 중심) 근접 + OSM 품질신호 순으로 상위 6곳
  const lodging: CityLodging[] = resolved.map((b) => ({
    city: b.city,
    options: rankHotels(b.hotels, b.pois, b.ctx!.center),
  }));

  const poiCount = allPois.filter(hasSourcedValue).length;
  const foodCount = allFood.filter(hasSourcedValue).length;
  notes.push(`수집 결과: 관광지 ${poiCount}곳 · 식당 ${foodCount}곳 (도시 ${resolved.length}개)`);
  if (poiCount === 0) {
    notes.push("관광지 출처(Overpass/Wikipedia)를 조회하지 못했습니다. 네트워크/외부 API 상태를 확인하세요.");
  }
  for (const b of bundles) {
    if (b.ctx === null) notes.push(`'${b.city}' 컨텍스트 조회 실패로 해당 도시 일정을 비웠습니다.`);
  }

  // 도시 간 이동방법
  const cityNodes: CityNode[] = resolved.map((b) => ({ name: b.city, center: b.ctx!.center }));
  const transfers = planTransfers(cityNodes);

  // 예산 (검증 통과 데이터만 사용). 국내(KR)면 원화 기준.
  const domestic = firstCtx.country_code === "KR";
  const baseBudgetInput = {
    currency,
    pois: allPois.filter(hasSourcedValue),
    food: allFood.filter(hasSourcedValue),
    transfers,
    flights,
    days: nDays,
    nights: Math.max(nDays - 1, 0),
    party: query.party,
    domestic,
    ...(query.budget_krw !== undefined ? { budget_krw: query.budget_krw } : {}),
  };
  let budget = estimateBudget({ ...baseBudgetInput, tier: "standard" });
  // 예산 초과 시 최소비용으로 재구성
  if (query.budget_krw !== undefined && budget.total_krw > query.budget_krw) {
    budget = estimateBudget({ ...baseBudgetInput, tier: "budget" });
  }

  const allFacts: VerifiedFact<unknown>[] = [
    ...allPois,
    ...allFood,
    ...weather,
    ...flights,
    ...(currency ? [currency] : []),
    ...(logistics ? [logistics] : []),
  ];

  return {
    query,
    destination_center: firstCtx.center,
    cities: resolved.map((b) => ({ name: b.city, center: b.ctx!.center })),
    days,
    lodging,
    transfers,
    budget,
    currency,
    weather,
    logistics,
    flights,
    verification_summary: summarize(allFacts),
    notes,
  };
}

/** 한 도시의 일정/데이터를 조립한다. 컨텍스트 실패 시 빈 날짜 블록을 돌려준다. */
async function buildCity(
  query: TripQuery,
  deps: PipelineDeps,
  city: string,
  startDayIndex: number,
  block: number,
  primaryMode: TripQuery["transport"][number],
): Promise<CityBundle> {
  const dates = Array.from({ length: block }, (_, i) => addDays(query.start_date, startDayIndex + i));

  const ctx = await safe(() => deps.resolveContext(city, query), null, 8_000);
  if (!ctx) {
    return { city, ctx: null, pois: [], food: [], hotels: [], weather: [], days: dates.map((d) => emptyDay(d, city)) };
  }

  const [pois, food, hotels, weather] = await Promise.all([
    safe(() => deps.collectPois(ctx, query), [] as VerifiedFact<Poi>[], 26_000), // 관광지 수집 우선(넉넉히)
    safe(() => deps.collectFood(ctx, query), [] as VerifiedFact<Restaurant>[], 16_000),
    safe(() => deps.collectHotels(ctx, query), [] as VerifiedFact<Hotel>[], 14_000),
    safe(
      () => deps.collectWeather(ctx, dates[0]!, dates[dates.length - 1]!),
      [] as VerifiedFact<WeatherDay>[],
      10_000,
    ),
  ]);

  const renderablePois = pois.filter(hasSourcedValue);
  const renderableFood = food.filter(hasSourcedValue);
  const places: Place[] = renderablePois.map((f, i) => ({
    id: `${city}-poi-${i}`,
    location: f.value.location,
    ...(f.value.time_pref ? { time_pref: f.value.time_pref } : {}),
  }));
  // 라우팅(이동시간 매트릭스)은 외부 API(OSRM) 의존 → 느리거나 실패해도 일정이 비지
  // 않도록 상한(12s) + 네트워크 불필요 폴백(순차 균등 배정)을 둔다.
  const route: RoutePlan = places.length > 0
    ? await safe(() => deps.buildRoute(places, block, primaryMode), fallbackRoute(places, block), 12_000)
    : { days: [], estimated: true, source_name: "" };
  const poiById = new Map(places.map((p, i) => [p.id, renderablePois[i]!] as const));
  // 식당 풀(품질 순위 보존) — 각 날의 관광 동선 근처의 상위 맛집을 배정한다.
  const foodPool = renderableFood.map((f, i) => ({ fact: f, rank: i }));

  const days: ItineraryDay[] = dates.map((date, localIdx) => {
    const weekday = new Date(date + "T00:00:00Z").getUTCDay();
    const dayRoute = route.days[localIdx];
    const orderedPois = (dayRoute?.ordered_place_ids ?? []).map((id) => poiById.get(id)!).filter(Boolean);
    const legMinutes = (dayRoute?.leg_seconds ?? orderedPois.map(() => 0)).map((s) => Math.round(s / 60));
    // 그날 방문지 중심 → 근처의 (품질+근접) 상위 식당 2곳(점심·저녁) 배정
    const dayCenter = poiCentroid(orderedPois) ?? ctx.center;
    const meals = pickNearbyFood(foodPool, dayCenter, 2);
    const input: DayAssemblyInput = {
      date,
      weekday,
      city,
      pois: orderedPois,
      legMinutes,
      legMode: primaryMode,
      legEstimated: route.estimated,
      legSource: route.source_name || "n/a",
      ...(meals[0] ? { lunch: meals[0] } : {}),
      ...(meals[1] ? { dinner: meals[1] } : {}),
    };
    return assembleDay(input);
  });

  return { city, ctx, pois, food, hotels, weather, days };
}

/** 그날 방문지들의 중심 좌표. 방문지가 없으면 null. */
function poiCentroid(pois: VerifiedFact<Poi>[]): GeoPoint | null {
  const pts = pois.filter(hasSourcedValue).map((p) => p.value.location);
  return pts.length > 0 ? centroidOf(pts) : null;
}

/**
 * 식당 풀에서 '동선 근처 + 품질 상위' n곳을 골라 반환하고 풀에서 제거한다.
 * 점수 = 중심까지 거리(km) + 품질순위 가중(0.12) — 낮을수록 우선.
 * → 그날 관광지 근처의 제대로 된 맛집이 배정된다(같은 식당 중복 방지).
 */
function pickNearbyFood(
  pool: { fact: VerifiedFact<Restaurant>; rank: number }[],
  center: GeoPoint,
  n: number,
): VerifiedFact<Restaurant>[] {
  const picked: VerifiedFact<Restaurant>[] = [];
  for (let k = 0; k < n && pool.length > 0; k++) {
    let bestIdx = 0;
    let bestCost = Infinity;
    for (let i = 0; i < pool.length; i++) {
      const loc = pool[i]!.fact.value?.location;
      if (!loc) continue;
      const km = haversineMeters(loc, center) / 1000;
      const cost = km + pool[i]!.rank * 0.12;
      if (cost < bestCost) {
        bestCost = cost;
        bestIdx = i;
      }
    }
    picked.push(pool.splice(bestIdx, 1)[0]!.fact);
  }
  return picked;
}

/**
 * 라우팅 실패/시간초과 시의 폴백 경로 — 외부 API 없이 장소를 날짜별로 순차 균등
 * 배정한다. 동선 최적화는 없지만 '수집된 POI 가 있는데 일정이 빈' 상황을 막는다.
 */
function fallbackRoute(places: Place[], days: number): RoutePlan {
  const k = Math.max(days, 1);
  const per = Math.ceil(places.length / k);
  const dayRoutes: DayRoute[] = [];
  for (let d = 0; d < k; d++) {
    const slice = places.slice(d * per, (d + 1) * per);
    dayRoutes.push({
      day_index: d,
      ordered_place_ids: slice.map((p) => p.id),
      leg_seconds: slice.map(() => 0),
      total_travel_seconds: 0,
    });
  }
  return { days: dayRoutes, estimated: true, source_name: "순차 배정(라우팅 미조회)" };
}

/**
 * 도시 추천 숙소 랭킹 — 실존 OSM 호텔을 '동선 중심(관광지 평균 좌표) 근접 + 품질신호'로
 * 정렬해 상위 6곳. 리뷰·요금을 지어내지 않고(§0) 근접도/성급/위키등재만 근거로 한다.
 */
function rankHotels(
  hotels: VerifiedFact<Hotel>[],
  pois: VerifiedFact<Poi>[],
  cityCenter: GeoPoint,
): VerifiedFact<Hotel>[] {
  const sourced = hotels.filter(hasSourcedValue);
  if (sourced.length === 0) return [];
  const poiPts = pois.filter(hasSourcedValue).map((p) => p.value.location);
  const center = poiPts.length > 0 ? centroidOf(poiPts) : cityCenter;
  const score = (f: (typeof sourced)[number]): number => {
    const h = f.value;
    const km = haversineMeters(h.location, center) / 1000;
    let s = -km; // 동선 중심에 가까울수록 높음(가성비·이동편의)
    if (h.stars) s += h.stars * 0.6; // 성급(있을 때만)
    if (h.kind === "hostel" || h.kind === "guest_house") s += 0.3; // 가성비 유형 소폭 우대
    return s;
  };
  return [...sourced].sort((a, b) => score(b) - score(a)).slice(0, 6);
}

function centroidOf(pts: GeoPoint[]): GeoPoint {
  const s = pts.reduce((a, p) => ({ lat: a.lat + p.lat, lng: a.lng + p.lng }), { lat: 0, lng: 0 });
  return { lat: s.lat / pts.length, lng: s.lng / pts.length };
}

function emptyDay(date: string, city: string): ItineraryDay {
  return {
    date,
    weekday: new Date(date + "T00:00:00Z").getUTCDay(),
    city,
    items: [],
    total_activity_minutes: 0,
    total_travel_minutes: 0,
    travel_ratio: 0,
    warnings: [],
  };
}

function emptyItinerary(query: TripQuery, nDays: number, cityNames: string[], note: string): Itinerary {
  const days: ItineraryDay[] = [];
  const alloc = allocateNights(nDays, cityNames.length);
  let idx = 0;
  cityNames.forEach((city, ci) => {
    for (let i = 0; i < alloc[ci]!; i++) days.push(emptyDay(addDays(query.start_date, idx++), city));
  });
  return {
    query,
    destination_center: { lat: 0, lng: 0 },
    cities: [],
    days,
    lodging: [],
    transfers: [],
    budget: {
      currency: null,
      lines: [],
      total_krw: 0,
      verified_krw: 0,
      per_person_krw: 0,
      note: "데이터 부족으로 예산을 산출하지 못했습니다.",
      tier: "standard",
      over_budget: false,
      shortfall_krw: 0,
      domestic: false,
    },
    currency: null,
    weather: [],
    logistics: null,
    flights: [],
    verification_summary: { high: 0, medium: 0, low: 0, total: 0, high_ratio: 0 },
    notes: [note],
  };
}

function addDays(date: string, d: number): string {
  return new Date(Date.parse(date) + d * 86_400_000).toISOString().slice(0, 10);
}

/**
 * 수집 함수를 실행하되 예외/시간초과 시 fallback 반환.
 * 서버리스(60s) 한도를 넘기지 않도록 각 단계에 상한을 둔다.
 */
async function safe<T>(fn: () => Promise<T>, fallback: T, ms = 18_000): Promise<T> {
  try {
    return await Promise.race([
      fn(),
      new Promise<T>((resolve) => setTimeout(() => resolve(fallback), ms)),
    ]);
  } catch {
    return fallback;
  }
}
