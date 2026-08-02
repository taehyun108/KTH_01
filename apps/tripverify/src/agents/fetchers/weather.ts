import "server-only";
import type { GeoPoint, WeatherDay } from "@/core/types/domains";
import type { Observation } from "@/core/verification/observation";
import type { SourceReader } from "../types";
import { fetchJson, nowISO } from "@/lib/http";

export interface WeatherArgs {
  center: GeoPoint;
  start_date: string; // YYYY-MM-DD
  end_date: string; // YYYY-MM-DD
}

/** 예보 최대 일수(16일 이내) 판단(§2). */
function daysBetween(a: string, b: string): number {
  return Math.round((Date.parse(b) - Date.parse(a)) / 86_400_000);
}

/** Open-Meteo (키 불필요, 기본 소스; tier 2). 16일 이내는 forecast. */
export const openMeteoReader: SourceReader<WeatherArgs, WeatherDay> = async ({
  center,
  start_date,
  end_date,
}) => {
  const span = daysBetween(start_date, end_date) + 1;
  const forecastDays = Math.min(Math.max(span, 1), 16);
  const url =
    `https://api.open-meteo.com/v1/forecast?latitude=${center.lat}&longitude=${center.lng}` +
    `&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max` +
    `&forecast_days=${forecastDays}&timezone=auto`;
  const data = await fetchJson<OpenMeteoResp>(url);
  return toWeatherObs(data, "forecast", {
    name: "Open-Meteo",
    url: "https://open-meteo.com/",
    tier: 2,
  });
};

/** Open-Meteo 기후 평년값(과거 재분석; tier 2, 별도 도메인 아님 — 독립성 낮음). */
export const openMeteoClimateReader: SourceReader<WeatherArgs, WeatherDay> = async ({
  center,
  start_date,
  end_date,
}) => {
  const url =
    `https://climate-api.open-meteo.com/v1/climate?latitude=${center.lat}&longitude=${center.lng}` +
    `&start_date=${start_date}&end_date=${end_date}` +
    `&models=EC_Earth3P_HR&daily=temperature_2m_max,temperature_2m_min`;
  const data = await fetchJson<OpenMeteoResp>(url);
  return toWeatherObs(data, "climatology", {
    name: "Open-Meteo Climate",
    url: "https://open-meteo.com/en/docs/climate-api",
    tier: 2,
  });
};

interface OpenMeteoResp {
  daily?: {
    time?: string[];
    temperature_2m_max?: number[];
    temperature_2m_min?: number[];
    precipitation_probability_max?: (number | null)[];
  };
}

function toWeatherObs(
  data: OpenMeteoResp,
  kind: WeatherDay["kind"],
  source: { name: string; url: string; tier: 1 | 2 | 3 },
): Observation<WeatherDay>[] {
  const d = data.daily;
  if (!d?.time) return [];
  const retrieved_at = nowISO();
  const out: Observation<WeatherDay>[] = [];
  for (let i = 0; i < d.time.length; i++) {
    const max = d.temperature_2m_max?.[i];
    const min = d.temperature_2m_min?.[i];
    const date = d.time[i];
    if (date === undefined || max === undefined || min === undefined) continue;
    const pop = d.precipitation_probability_max?.[i];
    out.push({
      value: {
        date,
        temp_max_c: max,
        temp_min_c: min,
        ...(typeof pop === "number" ? { precipitation_probability: pop } : {}),
        kind,
      },
      source: { ...source, retrieved_at },
      pass: source.tier === 1 ? 1 : 2,
    });
  }
  return out;
}

export const liveWeatherReaders: SourceReader<WeatherArgs, WeatherDay>[] = [
  openMeteoReader,
];
