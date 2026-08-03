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
import { SourcePanel, type SourcePanelData } from "@/components/SourcePanel";

const MapView = dynamic(() => import("@/components/MapView").then((m) => m.MapView), {
  ssr: false,
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

const DEFAULT_QUERY: TripQuery = {
  origin: "ICN",
  country: "Japan",
  destinations: ["Osaka", "Kyoto"],
  start_date: "2026-09-10",
  end_date: "2026-09-14",
  party: { adults: 2, children: 0 },
  budget_krw: 2_000_000,
  style: ["history", "food"],
  transport: ["transit"],
};

export default function Home() {
  const [form, setForm] = useState<TripQuery>(DEFAULT_QUERY);
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
  const it = plan.data;

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
    <main className="mx-auto max-w-4xl p-6">
      <header className="mb-6">
        <h1 className="text-2xl font-bold">TripVerify</h1>
        <p className="text-sm opacity-70">
          검증되지 않은 정보는 보여주지 않습니다 — 일정·이동·예산 모두 출처와 신뢰도를 표기합니다.
        </p>
      </header>

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

        <button type="submit" disabled={plan.isPending}
          className="w-full rounded-lg bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-700 disabled:opacity-50">
          {plan.isPending ? "검증 중…" : "검증된 일정 생성"}
        </button>
      </form>

      {plan.isError && (
        <p className="mb-4 rounded bg-red-50 p-3 text-sm text-red-800 dark:bg-red-950/40 dark:text-red-300">
          생성 실패: {(plan.error as Error).message}
        </p>
      )}

      {it && (
        <div className="space-y-4">
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
          {tab === "map" && <MapView itinerary={it} />}
          {tab === "report" && <VerificationReport itinerary={it} onSelect={select} />}
        </div>
      )}

      <SourcePanel data={panel} onClose={() => setPanel(null)} />
    </main>
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
