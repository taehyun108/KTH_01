import type { WeatherDay } from "@/core/types/domains";
import type { VerifiedFact } from "@/core/types/verified-fact";
import type { Comparator, Observation } from "@/core/verification/observation";
import type { SourceReader } from "./types";
import type { WeatherArgs } from "./fetchers/weather";
import { verify } from "@/core/verification/verifier";

/**
 * 날씨 값 비교자: 기온은 절대오차(±3°C) 허용, kind(예보/평년) 일치 요구.
 * 예보는 소스별 미세 편차가 정상이므로 상대오차가 아닌 절대오차를 쓴다.
 */
const TEMP_TOLERANCE_C = 3;
const weatherComparator: Comparator<WeatherDay> = {
  agree: (a, b) =>
    a.kind === b.kind &&
    Math.abs(a.temp_max_c - b.temp_max_c) <= TEMP_TOLERANCE_C &&
    Math.abs(a.temp_min_c - b.temp_min_c) <= TEMP_TOLERANCE_C,
  deviation: (adopted, other) =>
    Math.max(
      Math.abs(adopted.temp_max_c - other.temp_max_c),
      Math.abs(adopted.temp_min_c - other.temp_min_c),
    ),
};

/**
 * weather-agent (§2). 여러 소스의 일자별 관측을 날짜별로 묶어 각각 교차검증한다.
 * 날씨는 60초 내 변하지 않으므로 시간차 재조회를 강제하지 않는다(정보 안정성).
 */
export async function weatherAgent(
  args: WeatherArgs,
  readers: SourceReader<WeatherArgs, WeatherDay>[],
): Promise<VerifiedFact<WeatherDay>[]> {
  const settled = await Promise.allSettled(readers.map((r) => r(args)));
  const all = settled.flatMap((s) => (s.status === "fulfilled" ? s.value : []));

  // 날짜별로 관측을 그룹핑
  const byDate = new Map<string, Observation<WeatherDay>[]>();
  for (const o of all) {
    const arr = byDate.get(o.value.date) ?? [];
    arr.push(o);
    byDate.set(o.value.date, arr);
  }

  const dates = [...byDate.keys()].sort();
  return dates.map((date) =>
    verify<WeatherDay>(byDate.get(date)!, {
      comparator: weatherComparator,
      tolerance: TEMP_TOLERANCE_C,
    }),
  );
}
