import "server-only";
import type { PipelineDeps } from "./run";
import type { GeoContext, TripQuery } from "@/agents/types";
import { resolveContextLive } from "@/agents/fetchers/context";
import { resolveContextOffline } from "@/agents/offline/geocode";
import { dateHolidaysReader } from "@/agents/offline/holidays";
import { discoverPois, discoverRestaurants, wikiNearby } from "@/agents/fetchers/osm-discovery";
import { buildPoiFacts, buildRestaurantFacts } from "@/agents/poi-build";
import { selectPois, wikiFallbackSeeds, mergeByProximity } from "@/agents/poi-select";
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
/** 온라인 지오코딩 우선, 실패 시 오프라인(GeoNames 번들) 폴백 — 무네트워크에서도 컨텍스트 확보. */
async function resolveContextResilient(city: string, q: TripQuery): Promise<GeoContext> {
  try {
    return await resolveContextLive(city, q);
  } catch {
    return resolveContextOffline(city, q);
  }
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
      // 도시당 일수에 맞춰 상위 장소만 컨셉·유명도로 선별(무명/무관 장소 제외).
      const cities = Math.max(q.destinations.length, 1);
      const perCityDays = Math.max(1, Math.round(dayCount(q.start_date, q.end_date) / cities));
      const limit = Math.min(Math.max(perCityDays * 6, 8), 40);
      const selected = selectPois(merged, wiki, {
        ...(q.concept ? { concept: q.concept } : {}),
        styles: q.style,
        limit,
      });
      const osmPoints = overpassSeeds.map((s) => s.location);
      return buildPoiFacts(selected, osmPoints, wiki);
    },

    collectFood: async (ctx) => {
      const seeds = await discoverRestaurants(ctx.center).catch(() => []);
      return buildRestaurantFacts(seeds);
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
