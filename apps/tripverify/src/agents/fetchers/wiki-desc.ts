import "server-only";
import { fetchJson } from "@/lib/http";

/**
 * Wikipedia 요약 설명 배치 조회 — 추천 사유의 실제 근거(§0).
 * 여러 제목을 한 번에 조회하고, 폐관/철거 등 defunct 판별에도 쓴다.
 */
interface WikiQueryResp {
  query?: {
    normalized?: { from: string; to: string }[];
    redirects?: { from: string; to: string }[];
    pages?: Record<string, { title: string; extract?: string; description?: string; missing?: string }>;
  };
}

export interface WikiDesc {
  description?: string; // 짧은 설명(위키데이터)
  extract?: string; // 첫 문단 요약
}

/** 제목 목록 → 제목별 설명 맵. 배치(20개씩), 원제목 기준 매핑. */
export async function wikiDescriptions(titles: string[]): Promise<Map<string, WikiDesc>> {
  const out = new Map<string, WikiDesc>();
  const uniq = [...new Set(titles)].filter(Boolean);
  for (let i = 0; i < uniq.length; i += 20) {
    const chunk = uniq.slice(i, i + 20);
    try {
      const url =
        `https://en.wikipedia.org/w/api.php?action=query&format=json&redirects=1` +
        `&prop=extracts|description&exintro=1&explaintext=1&exlimit=max` +
        `&titles=${encodeURIComponent(chunk.join("|"))}`;
      const data = await fetchJson<WikiQueryResp>(url);
      // 원제목 → 최종제목 매핑(정규화/리다이렉트)
      const alias = new Map<string, string>();
      for (const n of data.query?.normalized ?? []) alias.set(n.from, n.to);
      for (const r of data.query?.redirects ?? []) alias.set(r.from, r.to);
      const byTitle = new Map<string, WikiDesc>();
      for (const p of Object.values(data.query?.pages ?? {})) {
        if (p.missing !== undefined) continue;
        byTitle.set(p.title, {
          ...(p.description ? { description: p.description } : {}),
          ...(p.extract ? { extract: truncate(p.extract) } : {}),
        });
      }
      for (const orig of chunk) {
        const finalTitle = resolveAlias(orig, alias);
        const d = byTitle.get(finalTitle) ?? byTitle.get(orig);
        if (d) out.set(orig, d);
      }
    } catch {
      // 조회 실패는 무시(사유가 없을 뿐)
    }
  }
  return out;
}

function resolveAlias(title: string, alias: Map<string, string>): string {
  let t = title;
  for (let i = 0; i < 3 && alias.has(t); i++) t = alias.get(t)!;
  return t;
}

function truncate(s: string): string {
  const clean = s.replace(/\s+/g, " ").trim();
  if (clean.length <= 160) return clean;
  const cut = clean.slice(0, 160);
  const lastDot = cut.lastIndexOf(". ");
  return (lastDot > 60 ? cut.slice(0, lastDot + 1) : cut) + "…";
}
