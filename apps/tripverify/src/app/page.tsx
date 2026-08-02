"use client";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import type { Itinerary } from "@/core/types/itinerary";
import type { VerifiedFact } from "@/core/types/verified-fact";
import type { TripQuery } from "@/agents/types";
import { Timeline } from "@/components/Timeline";
import { WeatherStrip } from "@/components/WeatherStrip";
import { BudgetDashboard } from "@/components/BudgetDashboard";
import { VerificationReport } from "@/components/VerificationReport";
import { SourcePanel, type SourcePanelData } from "@/components/SourcePanel";

const MapView = dynamic(() => import("@/components/MapView").then((m) => m.MapView), {
  ssr: false,
  loading: () => <div className="h-[420px] animate-pulse rounded-lg bg-black/5 dark:bg-white/5" />,
});

type Tab = "timeline" | "map" | "report";

const DEFAULT_QUERY: TripQuery = {
  origin: "ICN",
  destination: "Osaka",
  start_date: "2026-09-10",
  end_date: "2026-09-14",
  travelers: 2,
  budget_krw: 1_500_000,
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

  return (
    <main className="mx-auto max-w-4xl p-6">
      <header className="mb-6">
        <h1 className="text-2xl font-bold">TripVerify</h1>
        <p className="text-sm opacity-70">
          검증되지 않은 정보는 보여주지 않습니다 — 모든 항목에 출처와 신뢰도를 표기합니다.
        </p>
      </header>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          plan.mutate(form);
        }}
        className="mb-6 grid grid-cols-2 gap-3 rounded-lg border border-black/10 p-4 sm:grid-cols-4 dark:border-white/10"
      >
        <Field label="출발지">
          <input className="input" value={form.origin} onChange={(e) => setForm({ ...form, origin: e.target.value })} />
        </Field>
        <Field label="목적지">
          <input className="input" value={form.destination} onChange={(e) => setForm({ ...form, destination: e.target.value })} />
        </Field>
        <Field label="출발일">
          <input type="date" className="input" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} />
        </Field>
        <Field label="종료일">
          <input type="date" className="input" value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} />
        </Field>
        <Field label="인원">
          <input type="number" min={1} className="input" value={form.travelers} onChange={(e) => setForm({ ...form, travelers: Number(e.target.value) })} />
        </Field>
        <Field label="예산(원)">
          <input type="number" className="input" value={form.budget_krw ?? ""} onChange={(e) => setForm({ ...form, budget_krw: Number(e.target.value) })} />
        </Field>
        <div className="col-span-2 flex items-end sm:col-span-2">
          <button
            type="submit"
            disabled={plan.isPending}
            className="w-full rounded-lg bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {plan.isPending ? "검증 중…" : "검증된 일정 생성"}
          </button>
        </div>
      </form>

      {plan.isError && (
        <p className="mb-4 rounded bg-red-50 p-3 text-sm text-red-800 dark:bg-red-950/40 dark:text-red-300">
          생성 실패: {(plan.error as Error).message}
        </p>
      )}

      {it && (
        <>
          <div className="mb-4">
            <WeatherStrip weather={it.weather} onSelect={select} />
          </div>
          <div className="mb-4">
            <BudgetDashboard
              currency={it.currency}
              {...(it.query.budget_krw !== undefined ? { budgetKrw: it.query.budget_krw } : {})}
              onSelect={select}
            />
          </div>

          <nav className="mb-4 flex gap-2 border-b border-black/10 dark:border-white/10">
            {(["timeline", "map", "report"] as Tab[]).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`px-3 py-2 text-sm ${tab === t ? "border-b-2 border-blue-600 font-medium" : "opacity-60"}`}
              >
                {t === "timeline" ? "일정" : t === "map" ? "지도" : "검증 리포트"}
              </button>
            ))}
          </nav>

          {tab === "timeline" && <Timeline days={it.days} onSelect={select} />}
          {tab === "map" && <MapView itinerary={it} />}
          {tab === "report" && <VerificationReport itinerary={it} onSelect={select} />}
        </>
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
