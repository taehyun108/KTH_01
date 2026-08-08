import type { TripQuery } from "@/agents/types";
import type { Itinerary } from "@/core/types/itinerary";
import { runPipeline } from "@/pipeline/run";
import { liveDeps } from "@/pipeline/live-deps";
import { Planner } from "@/components/Planner";

// 예시 일정을 자주 갱신(ISR 2분) → 최신 코드/데이터가 빨리 반영되도록.
export const revalidate = 120;

function defaultQuery(): TripQuery {
  const d = (offset: number) =>
    new Date(Date.now() + offset * 86_400_000).toISOString().slice(0, 10);
  return {
    origin: "ICN",
    country: "Japan",
    destinations: ["Osaka", "Kyoto"],
    start_date: d(14),
    end_date: d(18),
    party: { adults: 2, children: 0 },
    budget_krw: 2_000_000,
    style: ["history", "food"],
    transport: ["transit"],
    concept: "유명 명소와 미식 위주로 느긋하게",
  };
}

/** 서버에서 예시 일정을 생성. 느리거나 실패해도 페이지는 항상 렌더된다. */
async function buildExample(q: TripQuery): Promise<Itinerary | null> {
  try {
    const timeout = new Promise<null>((resolve) => setTimeout(() => resolve(null), 20_000));
    return await Promise.race([runPipeline(q, liveDeps()), timeout]);
  } catch {
    return null;
  }
}

export default async function Home() {
  const q = defaultQuery();
  const example = await buildExample(q);
  const high = example?.verification_summary.high ?? 0;
  const total = example?.verification_summary.total ?? 0;

  return (
    <main className="mx-auto max-w-4xl p-6">
      {/* 히어로 — 열자마자 보이는 소개 콘텐츠 */}
      <section className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight">TripVerify</h1>
        <p className="mt-2 text-lg opacity-80">
          검증된 여행계획. <b>확인되지 않은 정보는 보여주지 않습니다.</b>
        </p>
        <p className="mt-1 text-sm opacity-70">
          일정·이동·예산의 모든 항목을 독립 출처 3곳 이상에서 교차검증하고, 출처 URL·조회시각·신뢰도를
          함께 표기합니다. 지어낸 정보(환각)를 원천 차단합니다.
        </p>
        <div className="mt-4 grid grid-cols-3 gap-3 text-center text-sm">
          <Stat emoji="🟢" label="검증됨(high)" sub="독립 3출처 일치" />
          <Stat emoji="🟡" label="부분검증(medium)" sub="2출처 교차확인" />
          <Stat emoji="🔴" label="단일출처(low)" sub="1출처 · 참고" />
        </div>
      </section>

      {/* 예시 일정 요약 배지 */}
      {example && (
        <section className="mb-6 rounded-lg border border-black/10 p-4 dark:border-white/10">
          <h2 className="text-sm font-semibold opacity-80">
            예시: {q.destinations.join(" · ")} {q.start_date} ~ {q.end_date}
          </h2>
          <p className="mt-1 text-xs opacity-60">
            검증 FACT {total}건 중 🟢{high}건 · 1인 예산 약{" "}
            {example.budget.per_person_krw.toLocaleString("ko-KR")}원(추정 포함)
          </p>
        </section>
      )}

      <Planner initial={example} defaultQuery={q} />

      <footer className="mt-10 border-t border-black/10 pt-4 text-xs opacity-50 dark:border-white/10">
        무료·무키 소스(Open-Meteo · OpenStreetMap · OSRM · frankfurter · Nager.Date) +
        오프라인 데이터(GeoNames · date-holidays)로 동작합니다. 검증되지 않은 값은 표시하지 않습니다.
      </footer>
    </main>
  );
}

function Stat({ emoji, label, sub }: { emoji: string; label: string; sub: string }) {
  return (
    <div className="rounded-lg border border-black/10 p-3 dark:border-white/10">
      <div className="text-xl">{emoji}</div>
      <div className="mt-1 font-medium">{label}</div>
      <div className="text-xs opacity-60">{sub}</div>
    </div>
  );
}
