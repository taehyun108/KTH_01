import "server-only";
import type { PipelineDeps } from "./run";
import type { GeoContext, TripQuery } from "@/agents/types";
import { resolveContextLive } from "@/agents/fetchers/context";
import { resolveContextOffline } from "@/agents/offline/geocode";
import { dateHolidaysReader } from "@/agents/offline/holidays";
import { discoverPois, discoverRestaurants, discoverHotels, wikiNearby } from "@/agents/fetchers/osm-discovery";
import { buildPoiFacts, buildRestaurantFacts, buildHotelFacts } from "@/agents/poi-build";
import { selectPois, wikiFallbackSeeds, mergeByProximity, isDefunctDescription, inferAllDay, isVisitorAttraction, fameScore } from "@/agents/poi-select";
import { wikiDescriptions } from "@/agents/fetchers/wiki-desc";
import { dayCount } from "@/agents/schema";
import { liveCurrencyReaders } from "@/agents/fetchers/currency";
import { liveWeatherReaders } from "@/agents/fetchers/weather";
import { liveLogisticsReaders } from "@/agents/fetchers/logistics";
import { matrixWithFallback } from "@/agents/fetchers/routing";
import { currencyAgent } from "@/agents/currency-agent";
import { weatherAgent } from "@/agents/weather-agent";
import { logisticsAgent } from "@/agents/logistics-agent";
import { routeAgent } from "@/agents/route-agent";
import { cachedVerify } from "@/db/repo";
import { unverified } from "@/core/factory/make-fact";
import type { CurrencyInfo as CurrencyInfoType } from "@/core/types/domains";
import { CurrencyInfoSchema, LogisticsInfoSchema } from "@/core/schema/domains.schema";

/**
 * 실 소스로 구성한 파이프라인 의존성 (§5 폴백 조합, 키 불필요).
 * 최적화: 안정적 도메인(환율/입국정보)은 cachedVerify 로 도메인별 TTL 캐시 + 감사 로그.
 * 네트워크 차단 환경에서는 각 collect 가 예외/빈값을 반환하고 파이프라인이 정직히 표기.
 */
/**
 * 온라인 지오코딩 우선, 실패/지연 시 오프라인(GeoNames 번들) 폴백.
 * Nominatim 이 클라우드에서 느리거나 막혀도, 6초 안에 오프라인으로 확실히 컨텍스트를
 * 확보한다(느린 Nominatim 때문에 상위 safe(8s) 캡에 걸려 빈 일정이 나오던 문제 해결).
 */
async function resolveContextResilient(city: string, q: TripQuery): Promise<GeoContext> {
  const timeout = new Promise<null>((resolve) => setTimeout(() => resolve(null), 6_000));
  try {
    const live = await Promise.race([resolveContextLive(city, q), timeout]);
    if (live) return live;
  } catch {
    // 온라인 실패 → 오프라인
  }
  return resolveContextOffline(city, q); // 번들 데이터(무네트워크) — 주요 도시 즉시 확보
}

export function liveDeps(): PipelineDeps {
  return {
    resolveContext: resolveContextResilient,

    collectPois: async (ctx, q) => {
      // Wikipedia(클라우드 안정) 주 소스 + Overpass 보강. 둘 다 best-effort.
      const [overpassSeeds, wiki] = await Promise.all([
        discoverPois(ctx.center).catch(() => []),
        wikiNearby(ctx.center).catch(() => []),
      ]);
      const merged = mergeByProximity(overpassSeeds, wikiFallbackSeeds(wiki));
      const cities = Math.max(q.destinations.length, 1);
      const perCityDays = Math.max(1, Math.round(dayCount(q.start_date, q.end_date) / cities));
      // 하루 4곳 목표(3곳+ 보장 & 점심·저녁 들어갈 여유). 너무 많으면 10시간 상한에
      // 걸려 식당이 밀려나므로 과하지 않게.
      const limit = Math.min(Math.max(perCityDays * 4, 6), 28);

      // 1차 넓게 선별(설명 조회 후 폐관·비검색 필터로 좁힘).
      const prelim = selectPois(merged, wiki, {
        ...(q.concept ? { concept: q.concept } : {}),
        styles: q.style,
        limit: Math.min(limit + 18, 45),
      });

      // 설명(특히 한국어 위키 2-hop) 조회는 비용이 크므로, 설명 없이 1차 유명도로
      // 정렬해 상위 후보(최대 24개)에만 조회한다 → 한국어 설명이 제때 도착.
      const preRanked = [...prelim].sort((a, b) => fameScore(b) - fameScore(a)).slice(0, Math.min(limit + 6, 24));

      // Wikipedia 설명 배치 조회(영어 제목 기준) → 추천 사유 근거(한국어 우선) + defunct 판별.
      const descKey = (s: (typeof preRanked)[number]) => s.name_en || s.name;
      const descMap = await Promise.race([
        wikiDescriptions(preRanked.map(descKey)).catch(() => new Map()),
        new Promise<Map<string, { description?: string; extract?: string }>>((resolve) =>
          setTimeout(() => resolve(new Map()), 14_000), // 한국어 위키 조회 여유(POI 목록은 항상 반환)
        ),
      ]);
      const enriched = preRanked.map((s) => {
        const d = descMap.get(descKey(s));
        const description = d?.extract ?? d?.description;
        return {
          ...s,
          ...(description ? { description } : {}),
          all_day: inferAllDay(s.name_en || s.name, s.categories),
        };
      });

      // 폐관/철거 제외 + 관공서·기업 제외. '설명 없는 위키 단독'은 카테고리(제목에서
      // 추론한 관광 유형)조차 없을 때만 버린다 — Overpass 가 클라우드에서 실패해 모든
      // 후보가 위키 단독이어도 유명 명소(예: 유원/사찰/타워)는 살아남게 한다(빈 일정 방지).
      const findable = enriched.filter((s) => {
        if (isDefunctDescription(s.description)) return false;
        if (!isVisitorAttraction(s)) return false; // 관공서·기업 등 비관광 제외
        const hasSignal = s.on_osm || !!s.description || (s.categories?.length ?? 0) > 0;
        if (s.origin === "wiki" && !hasSignal) return false; // 정보 전무한 위키 단독만 제외
        return true;
      });
      // 유명도 순 재정렬 → 무명보다 유명 명소를 상위로
      const ranked = findable.sort((a, b) => fameScore(b) - fameScore(a));
      // 안전망: 필터가 과해 비면, 폐관/비관광만 뺀 후보로라도 채운다(수집됐는데 빈 일정 방지)
      const pool = ranked.length > 0
        ? ranked
        : enriched
            .filter((s) => !isDefunctDescription(s.description) && isVisitorAttraction(s))
            .sort((a, b) => fameScore(b) - fameScore(a));
      const final = pool.slice(0, limit);
      const osmPoints = overpassSeeds.map((s) => s.location);
      return buildPoiFacts(final, osmPoints, wiki);
    },

    collectFood: async (ctx) => {
      const seeds = await discoverRestaurants(ctx.center).catch(() => []);
      return buildRestaurantFacts(seeds);
    },

    collectHotels: async (ctx) => {
      const seeds = await discoverHotels(ctx.center).catch(() => []);
      return buildHotelFacts(seeds);
    },

    collectCurrency: async (ctx) => {
      // 국내여행(원화)은 환전이 없으므로 환율 조회를 생략.
      if (ctx.currency_code === "KRW") {
        return unverified<CurrencyInfoType>("국내여행 — 원화 기준(환전 불필요)");
      }
      return cachedVerify({
        key: `currency:${ctx.currency_code}`,
        domain: "currency",
        agent: "currency-agent",
        valueSchema: CurrencyInfoSchema,
        produce: () => currencyAgent({ code: ctx.currency_code }, liveCurrencyReaders),
      }) as ReturnType<PipelineDeps["collectCurrency"]>;
    },

    collectWeather: (ctx, start, end) =>
      weatherAgent({ center: ctx.center, start_date: start, end_date: end }, liveWeatherReaders),

    // 항공: 키(Amadeus) 필요. 키 없으면 agent 가 unverified 반환.
    collectFlights: async () => [],

    collectLogistics: async (ctx, q) =>
      cachedVerify({
        key: `logistics:${ctx.country_code}:${q.start_date}:${q.end_date}`,
        domain: "logistics",
        agent: "logistics-agent",
        valueSchema: LogisticsInfoSchema,
        produce: () =>
          logisticsAgent(
            {
              country_code: ctx.country_code,
              year: Number(q.start_date.slice(0, 4)),
              start_date: q.start_date,
              end_date: q.end_date,
            },
            // 온라인 2소스 + 오프라인 date-holidays → 독립 3소스 교차검증 가능
            [...liveLogisticsReaders, dateHolidaysReader],
          ),
      }) as ReturnType<PipelineDeps["collectLogistics"]>,

    buildRoute: (places, days, mode) =>
      routeAgent({ places, days, mode }, matrixWithFallback()),
  };
}
