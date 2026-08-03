import "server-only";
import type { PipelineDeps } from "./run";
import { resolveContextLive } from "@/agents/fetchers/context";
import { discoverNames, livePoiReaders, liveFoodReaders } from "@/agents/fetchers/places";
import { liveCurrencyReaders } from "@/agents/fetchers/currency";
import { liveWeatherReaders } from "@/agents/fetchers/weather";
import { liveLogisticsReaders } from "@/agents/fetchers/logistics";
import { matrixWithFallback } from "@/agents/fetchers/routing";
import { poiAgent, foodAgent } from "@/agents/poi-agent";
import { currencyAgent } from "@/agents/currency-agent";
import { weatherAgent } from "@/agents/weather-agent";
import { logisticsAgent } from "@/agents/logistics-agent";
import { routeAgent } from "@/agents/route-agent";
import { cachedVerify } from "@/db/repo";
import { CurrencyInfoSchema, LogisticsInfoSchema } from "@/core/schema/domains.schema";

/**
 * 실 소스로 구성한 파이프라인 의존성 (§5 폴백 조합, 키 불필요).
 * 최적화: 안정적 도메인(환율/입국정보)은 cachedVerify 로 도메인별 TTL 캐시 + 감사 로그.
 * 네트워크 차단 환경에서는 각 collect 가 예외/빈값을 반환하고 파이프라인이 정직히 표기.
 */
export function liveDeps(): PipelineDeps {
  return {
    resolveContext: resolveContextLive,

    collectPois: async (ctx) => {
      const names = await discoverNames(ctx.center, "poi");
      return poiAgent(names, { center: ctx.center }, livePoiReaders);
    },

    collectFood: async (ctx) => {
      const names = await discoverNames(ctx.center, "food");
      return foodAgent(names, { center: ctx.center }, liveFoodReaders);
    },

    collectCurrency: async (ctx) =>
      cachedVerify({
        key: `currency:${ctx.currency_code}`,
        domain: "currency",
        agent: "currency-agent",
        valueSchema: CurrencyInfoSchema,
        produce: () => currencyAgent({ code: ctx.currency_code }, liveCurrencyReaders),
      }) as ReturnType<PipelineDeps["collectCurrency"]>,

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
            liveLogisticsReaders,
          ),
      }) as ReturnType<PipelineDeps["collectLogistics"]>,

    buildRoute: (places, days, mode) =>
      routeAgent({ places, days, mode }, matrixWithFallback()),
  };
}
