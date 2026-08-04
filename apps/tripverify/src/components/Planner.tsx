"use client";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import type { Itinerary } from "@/core/types/itinerary";
import type { VerifiedFact } from "@/core/types/verified-fact";
import type { TripQuery, TravelStyle, TransportMode } from "@/agents/types";
import { Timeline } from "@/components/Timeline";
import { WeatherStrip } from "@/components/WeatherStrip";
import { BudgetBreakdown } from "@/components/BudgetBreakdown";
import { Transfers } from "@/components/Transfers";
import { VerificationReport } from "@/components/VerificationReport";
import { ConceptSummary } from "@/components/ConceptSummary";
import { FlightLinks } from "@/components/FlightLinks";
import { LodgingLinks } from "@/components/LodgingLinks";
import { SourcePanel, type SourcePanelData } from "@/components/SourcePanel";

const GoogleMap = dynamic(() => import("@/components/GoogleMap").then((m) => m.GoogleMap), {
  loading: () => <div className="h-[420px] animate-pulse rounded-lg bg-black/5 dark:bg-white/5" />,
});

type Tab = "timeline" | "map" | "report";

const STYLES: { v: TravelStyle; l: string }[] = [
  { v: "relax", l: "휴양" },
  { v: "food", l: "미식" },
  { v: "history", l: "역사" },
  { v: "activity", l: "액티비티" },
];
const TRANSPORTS: { v: TransportMode; l: string }[] = [
  { v: "walk", l: "도보" },
  { v: "transit", l: "대중교통" },
  { v: "car", l: "렌터카" },
];

/**
 * 여행계획 인터랙티브 UI. 서버가 미리 만든 예시 일정(initial)을 첫 화면에 바로
 * 보여주고, 폼으로 조건을 바꿔 재생성할 수 있다.
 */
export function Planner({
  initial,
  defaultQuery,
}: {
  initial: Itinerary | null;
  defaultQuery: TripQuery;
}) {
  const [form, setForm] = useState<TripQuery>(defaultQuery);
  const [tab, setTab] = useState<Tab>("timeline");
  const [panel, setPanel] = useState<SourcePanelData | null>(null);

  const plan = useMutation({
    mutationFn: async (q: TripQuery): Promise<Itinerary> => {
      const res = await fetch("/api/plan", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(q),
      });
      if (!res.ok) throw new Error((await res.json()).error ?? `HTTP ${res.status}`);
      return res.json();
    },
  });

  const select = (fact: VerifiedFact<unknown>, title: string) => setPanel({ title, fact });
  // 서버 예시(initial)를 먼저 보여주고, 사용자가 생성하면 그 결과로 대체
  const it = plan.data ?? initial;

  const setCity = (idx: number, val: string) => {
    const d = [...form.destinations];
    d[idx] = val;
    setForm({ ...form, destinations: d });
  };
  const addCity = () => setForm({ ...form, destinations: [...form.destinations, ""] });
  const removeCity = (idx: number) =>
    setForm({ ...form, destinations: form.destinations.filter((_, i) => i !== idx) });
  const toggleStyle = (v: TravelStyle) =>
    setForm({
      ...form,
      style: form.style.includes(v) ? form.style.filter((s) => s !== v) : [...form.style, v],
    });

  return (
    <>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          plan.mutate({ ...form, destinations: form.destinations.filter((c) => c.trim()) });
        }}
        className="mb-6 space-y-4 rounded-lg border border-black/10 p-4 dark:border-white/10"
      >
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Field label="출발지">
            <input className="input" value={form.origin} onChange={(e) => setForm({ ...form, origin: e.target.value })} />
          </Field>
          <Field label="국가">
            <input className="input" value={form.country ?? ""} onChange={(e) => setForm({ ...form, country: e.target.value })} />
          </Field>
          <Field label="출발일">
            <input type="date" className="input" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} />
          </Field>
          <Field label="종료일">
            <input type="date" className="input" value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} />
          </Field>
        </div>

        <div>
          <span className="text-xs opacity-70">방문 도시 (순서대로)</span>
          <div className="mt-1 space-y-2">
            {form.destinations.map((c, i) => (
              <div key={i} className="flex gap-2">
                <input
                  className="input flex-1"
                  placeholder={`도시 ${i + 1}`}
                  value={c}
                  onChange={(e) => setCity(i, e.target.value)}
                />
                {form.destinations.length > 1 && (
                  <button type="button" onClick={() => removeCity(i)} className="rounded border px-2 text-sm">
                    ✕
                  </button>
                )}
              </div>
            ))}
            <button type="button" onClick={addCity} className="text-sm text-blue-600 underline">
              + 도시 추가
            </button>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Field label="성인">
            <input type="number" min={1} className="input" value={form.party.adults}
              onChange={(e) => setForm({ ...form, party: { ...form.party, adults: Number(e.target.value) } })} />
          </Field>
          <Field label="아동">
            <input type="number" min={0} className="input" value={form.party.children}
              onChange={(e) => setForm({ ...form, party: { ...form.party, children: Number(e.target.value) } })} />
          </Field>
          <Field label="예산(원)">
            <input type="number" className="input" value={form.budget_krw ?? ""}
              onChange={(e) => setForm({ ...form, budget_krw: Number(e.target.value) })} />
          </Field>
          <Field label="이동수단">
            <select className="input" value={form.transport[0]}
              onChange={(e) => setForm({ ...form, transport: [e.target.value as TransportMode] })}>
              {TRANSPORTS.map((t) => <option key={t.v} value={t.v}>{t.l}</option>)}
            </select>
          </Field>
        </div>

        <div>
          <span className="text-xs opacity-70">여행 스타일</span>
          <div className="mt-1 flex flex-wrap gap-2">
            {STYLES.map((s) => (
              <button key={s.v} type="button" onClick={() => toggleStyle(s.v)}
                className={`rounded-full border px-3 py-1 text-sm ${form.style.includes(s.v) ? "border-blue-600 bg-blue-50 dark:bg-blue-950/40" : "opacity-60"}`}>
                {s.l}
              </button>
            ))}
          </div>
        </div>

        <div>
          <span className="text-xs opacity-70">여행 컨셉 / 느낌 (자유 입력)</span>
          <textarea
            className="input mt-1 w-full"
            rows={2}
            placeholder="예) 유명 명소와 미식 위주로 느긋하게 / 역사·사찰 중심 / 인스타 감성 뷰맛집"
            value={form.concept ?? ""}
            onChange={(e) => setForm({ ...form, concept: e.target.value })}
          />
        </div>

        <button type="submit" disabled={plan.isPending}
          className="w-full rounded-lg bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-700 disabled:opacity-50">
          {plan.isPending ? "검증 중…" : "이 조건으로 다시 생성"}
        </button>
      </form>

      {plan.isError && (
        <p className="mb-4 rounded bg-red-50 p-3 text-sm text-red-800 dark:bg-red-950/40 dark:text-red-300">
          생성 실패: {(plan.error as Error).message}
        </p>
      )}

      {it ? (
        <div className="space-y-4">
          {plan.data == null && initial && (
            <p className="rounded bg-blue-50 p-2 text-xs text-blue-800 dark:bg-blue-950/40 dark:text-blue-300">
              아래는 예시 일정입니다. 위 폼에서 조건을 바꿔 나만의 검증된 일정을 만들어 보세요.
            </p>
          )}
          <ConceptSummary itinerary={it} />
          <FlightLinks itinerary={it} />
          <LodgingLinks itinerary={it} />
          <WeatherStrip weather={it.weather} onSelect={select} />
          <Transfers transfers={it.transfers} onSelect={select} />
          <BudgetBreakdown budget={it.budget} onSelect={select} />

          <nav className="flex gap-2 border-b border-black/10 dark:border-white/10">
            {(["timeline", "map", "report"] as Tab[]).map((t) => (
              <button key={t} onClick={() => setTab(t)}
                className={`px-3 py-2 text-sm ${tab === t ? "border-b-2 border-blue-600 font-medium" : "opacity-60"}`}>
                {t === "timeline" ? "일정" : t === "map" ? "지도" : "검증 리포트"}
              </button>
            ))}
          </nav>

          {tab === "timeline" && <Timeline days={it.days} onSelect={select} />}
          {tab === "map" && <GoogleMap itinerary={it} />}
          {tab === "report" && <VerificationReport itinerary={it} onSelect={select} />}
        </div>
      ) : (
        <p className="rounded-lg border border-black/10 p-6 text-center text-sm opacity-70 dark:border-white/10">
          위 폼에 여행 조건을 입력하고 <b>“이 조건으로 다시 생성”</b>을 누르면 검증된 일정이 나타납니다.
        </p>
      )}

      <SourcePanel data={panel} onClose={() => setPanel(null)} />
    </>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-xs">
      <span className="opacity-70">{label}</span>
      {children}
    </label>
  );
}
