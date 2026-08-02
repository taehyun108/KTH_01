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
import { dayCount } from "@/agents/schema";

/**
 * 실 소스로 구성한 파이프라인 의존성 (§5 폴백 조합, 키 불필요).
 * 네트워크가 허용된 환경에서 동작. 본 샌드박스처럼 외부 API 가 차단되면
 * 각 collect 가 예외/빈값을 반환하고 파이프라인이 notes 로 정직하게 표기한다.
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

    collectCurrency: (ctx) =>
      currencyAgent({ code: ctx.currency_code }, liveCurrencyReaders),

    collectWeather: (ctx, q) =>
      weatherAgent(
        { center: ctx.center, start_date: q.start_date, end_date: q.end_date },
        liveWeatherReaders,
      ),

    // 항공: 키(Amadeus) 필요. 키 없으면 agent 가 unverified 반환.
    collectFlights: async () => [],

    collectLogistics: (ctx, q) =>
      logisticsAgent(
        {
          country_code: ctx.country_code,
          year: Number(q.start_date.slice(0, 4)),
          start_date: q.start_date,
          end_date: q.end_date,
        },
        liveLogisticsReaders,
      ),

    buildRoute: (places, days, mode) =>
      routeAgent({ places, days, mode }, matrixWithFallback()),
  };
}

export { dayCount };
