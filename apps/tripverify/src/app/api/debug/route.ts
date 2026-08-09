import { NextResponse } from "next/server";
import type { TripQuery } from "@/agents/types";
import { resolveContextLive } from "@/agents/fetchers/context";
import { resolveContextOffline } from "@/agents/offline/geocode";
import { discoverPois, discoverRestaurants, wikiNearby } from "@/agents/fetchers/osm-discovery";
import { wikiDescriptions } from "@/agents/fetchers/wiki-desc";
import { runPipeline } from "@/pipeline/run";
import { liveDeps } from "@/pipeline/live-deps";
import { hasSourcedValue } from "@/core/types/verified-fact";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 60;

/**
 * 진단용: /api/debug?city=Shanghai
 * 각 외부 소스(지오코딩/Overpass/Wikipedia/설명)가 실제로 무엇을 반환하는지 확인.
 * 빈 일정 원인(네트워크? 소스? 필터?)을 정확히 짚기 위한 도구.
 */
export async function GET(req: Request) {
  const city = new URL(req.url).searchParams.get("city") ?? "Osaka";
  const q = { destinations: [city] } as TripQuery;

  // 1) 컨텍스트(좌표/국가)
  let ctx: Awaited<ReturnType<typeof resolveContextLive>> | null = null;
  let ctxSource = "live";
  try {
    ctx = await resolveContextLive(city, q);
  } catch {
    ctxSource = "offline";
    try {
      ctx = await resolveContextOffline(city, q);
    } catch {
      ctx = null;
    }
  }
  if (!ctx) {
    return NextResponse.json({ city, error: "geocode 실패(live·offline 모두)" }, { status: 200 });
  }

  const t0 = Date.now();
  // 2) 관광지 소스
  const [overpass, wiki] = await Promise.all([
    discoverPois(ctx.center)
      .then((r) => ({ ok: true, count: r.length, sample: r.slice(0, 6).map((s) => s.name) }))
      .catch((e) => ({ ok: false, error: String(e).slice(0, 200) })),
    wikiNearby(ctx.center)
      .then((r) => ({ ok: true, count: r.length, sample: r.slice(0, 10).map((w) => w.title) }))
      .catch((e) => ({ ok: false, error: String(e).slice(0, 200) })),
  ]);

  // 3) 설명 조회 확인(위키 상위 5개)
  const wikiTitles = "sample" in wiki && Array.isArray(wiki.sample) ? wiki.sample.slice(0, 5) : [];
  const descMap = await wikiDescriptions(wikiTitles).catch(() => new Map());
  const descriptions = Object.fromEntries([...descMap.entries()].map(([k, v]) => [k, v.extract ?? v.description ?? ""]));

  // 4) 식당 소스
  const restaurants = await discoverRestaurants(ctx.center)
    .then((r) => ({ ok: true, count: r.length, sample: r.slice(0, 5).map((s) => s.name) }))
    .catch((e) => ({ ok: false, error: String(e).slice(0, 200) }));

  // 5) 전체 파이프라인(수집→선별→클러스터→조립)까지 실제로 돌려 날짜별 항목 수 확인.
  //    수집은 되는데 일정이 비는지(조립 문제) vs 수집 자체가 비는지 구분.
  let pipeline: unknown = null;
  if (new URL(req.url).searchParams.get("full") !== "0") {
    try {
      const it = await runPipeline(
        {
          origin: "ICN",
          destinations: [city],
          start_date: "2026-08-09",
          end_date: "2026-08-11",
          party: { adults: 2, children: 0 },
          style: [],
          transport: ["transit"],
        } as TripQuery,
        liveDeps(),
      );
      pipeline = {
        pois_in_days: it.days.reduce((n, d) => n + d.items.filter((x) => x.kind === "poi").length, 0),
        food_in_days: it.days.reduce((n, d) => n + d.items.filter((x) => x.kind === "food").length, 0),
        notes: it.notes,
        days: it.days.map((d) => ({
          date: d.date,
          city: d.city,
          items: d.items.map((x) => ({ kind: x.kind, name: x.place.value?.name ?? x.name, sourced: hasSourcedValue(x.place) })),
        })),
      };
    } catch (e) {
      pipeline = { error: String(e).slice(0, 300) };
    }
  }

  return NextResponse.json({
    city,
    context: { source: ctxSource, center: ctx.center, country: ctx.country_code, currency: ctx.currency_code },
    elapsed_ms: Date.now() - t0,
    overpass,
    wiki,
    restaurants,
    descriptions_loaded: Object.keys(descriptions).length,
    descriptions,
    pipeline,
  });
}
