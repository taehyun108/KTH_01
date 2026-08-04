"use client";
import type { VerifiedFact } from "@/core/types/verified-fact";
import { ConfidenceBadge } from "./ConfidenceBadge";
import {
  isoToLocalTime,
  googleMapsPlace,
  googleMapsCoord,
  naverBlogSearch,
  naverMapSearch,
  searchName,
} from "@/lib/format";

/** 값이 좌표를 가진 '장소'인지 판별하고 좌표를 뽑는다. */
function placeLoc(value: unknown): { lat: number; lng: number } | null {
  if (value && typeof value === "object" && "location" in value) {
    const l = (value as { location?: { lat?: number; lng?: number } }).location;
    if (l && typeof l.lat === "number" && typeof l.lng === "number") {
      return { lat: l.lat, lng: l.lng };
    }
  }
  return null;
}

export interface SourcePanelData {
  title: string;
  fact: VerifiedFact<unknown>;
}

/** 항목 클릭 시 열리는 출처 사이드패널 (§8-2). 출처 3개 + 조회시각 + 근거 문구. */
export function SourcePanel({
  data,
  onClose,
}: {
  data: SourcePanelData | null;
  onClose: () => void;
}) {
  if (!data) return null;
  const { fact } = data;
  return (
    <aside className="fixed inset-y-0 right-0 z-40 w-full max-w-md overflow-y-auto border-l border-black/10 bg-white p-5 shadow-2xl dark:border-white/10 dark:bg-neutral-900">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">{data.title}</h2>
          <div className="mt-1">
            <ConfidenceBadge confidence={fact.confidence} />
          </div>
        </div>
        <button
          onClick={onClose}
          className="rounded px-2 py-1 text-sm hover:bg-black/5 dark:hover:bg-white/10"
          aria-label="닫기"
        >
          ✕
        </button>
      </div>

      {fact.unverified_reason && (
        <p className="mb-4 rounded bg-red-50 p-3 text-sm text-red-800 dark:bg-red-950/40 dark:text-red-300">
          확인 필요: {fact.unverified_reason}
        </p>
      )}

      {/* 장소면 구글지도/네이버 최신정보 바로가기 */}
      {placeLoc(fact.value) &&
        (() => {
          const sname = searchName(fact.value as never) || data.title;
          return (
            <div className="mb-4 grid grid-cols-2 gap-2 text-sm">
              <LinkBtn href={googleMapsPlace(sname)} label="🗺️ 구글지도" />
              <LinkBtn href={googleMapsCoord(placeLoc(fact.value)!)} label="📍 정확한 위치" />
              <LinkBtn href={naverBlogSearch(sname)} label="📝 네이버 블로그 후기" />
              <LinkBtn href={naverMapSearch(sname)} label="🧭 네이버 지도" />
            </div>
          );
        })()}

      <section className="mb-4">
        <h3 className="mb-2 text-sm font-semibold opacity-70">
          출처 {fact.sources.length}곳 · 교차동의 {fact.verification.agree_count} · Pass{" "}
          {fact.verification.passes_completed}/3
        </h3>
        <ul className="space-y-3">
          {fact.sources.map((s, i) => (
            <li key={i} className="rounded border border-black/10 p-3 text-sm dark:border-white/10">
              <div className="flex items-center justify-between">
                <a
                  href={s.url}
                  target="_blank"
                  rel="noreferrer"
                  className="font-medium text-blue-600 underline dark:text-blue-400"
                >
                  {s.name}
                </a>
                <span className="rounded bg-black/5 px-1.5 py-0.5 text-xs dark:bg-white/10">
                  tier {s.tier}
                </span>
              </div>
              <div className="mt-1 text-xs opacity-60">조회: {isoToLocalTime(s.retrieved_at)}</div>
              {s.excerpt && <p className="mt-1 text-xs italic opacity-80">“{s.excerpt}”</p>}
            </li>
          ))}
        </ul>
      </section>

      {fact.verification.conflicting_values && fact.verification.conflicting_values.length > 0 && (
        <details className="rounded border border-amber-300 bg-amber-50 p-3 text-sm dark:border-amber-800 dark:bg-amber-950/30">
          <summary className="cursor-pointer font-medium">
            채택하지 않은 상충 값 {fact.verification.conflicting_values.length}건
          </summary>
          <ul className="mt-2 space-y-2">
            {fact.verification.conflicting_values.map((c, i) => (
              <li key={i} className="text-xs">
                <code className="break-all">{JSON.stringify(c.value)}</code>
                <span className="opacity-60"> — {c.source.name}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </aside>
  );
}

function LinkBtn({ href, label }: { href: string; label: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="rounded border border-black/10 px-2 py-1.5 text-center hover:bg-black/5 dark:border-white/10 dark:hover:bg-white/5"
    >
      {label}
    </a>
  );
}
