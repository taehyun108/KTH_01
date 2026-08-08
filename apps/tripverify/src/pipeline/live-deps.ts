import "server-only";
import type { PipelineDeps } from "./run";
import type { GeoContext, TripQuery } from "@/agents/types";
import { resolveContextLive } from "@/agents/fetchers/context";
import { resolveContextOffline } from "@/agents/offline/geocode";
import { dateHolidaysReader } from "@/agents/offline/holidays";
import { discoverPois, discoverRestaurants, wikiNearby } from "@/agents/fetchers/osm-discovery";
import { buildPoiFacts, buildRestaurantFacts } from "@/agents/poi-build";
import { selectPois, wikiFallbackSeeds, mergeByProximity, isDefunctDescription, inferAllDay, isVisitorAttraction } from "@/agents/poi-select";
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
      const cities = Math.max(q.destinations.length, 1);
      const perCityDays = Math.max(1, Math.round(dayCount(q.start_date, q.end_date) / cities));
      const limit = Math.min(Math.max(perCityDays * 7, 12), 50); // 하루 3곳+ 확보용 넉넉히

      // 1차 넓게 선별(설명 조회 후 폐관·비검색 필터로 좁힘)
      const prelim = selectPois(merged, wiki, {
        ...(q.concept ? { concept: q.concept } : {}),
        styles: q.style,
        limit: limit * 2,
      });

      // Wikipedia 설명 배치 조회(영어 제목 기준) → 추천 사유 근거 + defunct 판별
      const descKey = (s: (typeof prelim)[number]) => s.name_en || s.name;
      const descMap = await wikiDescriptions(prelim.map(descKey)).catch(() => new Map());
      const enriched = prelim.map((s) => {
        const d = descMap.get(descKey(s));
        const description = d?.extract ?? d?.description;
        return {
          ...s,
          ...(description ? { description } : {}),
          all_day: inferAllDay(s.name_en || s.name, s.categories),
        };
      });

      // 폐관/철거 제외 + OSM 없고 설명도 없는(구글 미검색 위험) 위키 단독 제외.
      // 단, 설명 API 자체가 실패했으면(descMap 비어있음) 설명 없음으로 과도하게
      // 버리지 않는다(빈 일정 방지).
      const descWorked = descMap.size > 0;
      const findable = enriched.filter((s) => {
        if (isDefunctDescription(s.description)) return false;
        if (!isVisitorAttraction(s)) return false; // 관공서·기업 등 비관광 제외
        if (descWorked && !s.on_osm && s.origin === "wiki" && !s.description) return false;
        return true;
      });
      const final = findable.slice(0, limit);
      const osmPoints = overpassSeeds.map((s) => s.location);
      return buildPoiFacts(final, osmPoints, wiki);
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
