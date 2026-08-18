import "server-only";
import { fetchJson } from "@/lib/http";

/**
 * Wikipedia 요약 설명 배치 조회 — 추천 사유의 실제 근거(§0).
 * 한국인 사용자를 위해 '한국어 위키백과' 설명을 우선 사용한다. 영어 제목의 문서에
 * 연결된 한국어판(langlinks)이 있으면 그 한국어 요약을 쓰고, 없으면 영어 요약으로
 * 폴백한다(번역을 지어내지 않음 — 실제 한국어 문서가 있을 때만 한국어).
 */
interface WikiQueryResp {
  query?: {
    normalized?: { from: string; to: string }[];
    redirects?: { from: string; to: string }[];
    pages?: Record<
      string,
      {
        title: string;
        extract?: string;
        description?: string;
        missing?: string;
        langlinks?: { lang: string; "*": string }[];
      }
    >;
  };
}

export interface WikiDesc {
  description?: string; // 짧은 설명(위키데이터)
  extract?: string; // 첫 문단 요약(한국어 우선)
  title_ko?: string; // 한국어 위키백과 표제어(장소명 한국어 표기용)
}

/** 제목 목록 → 제목별 설명 맵(한국어 우선, 없으면 영어). 배치(20개씩, 병렬). */
export async function wikiDescriptions(titles: string[]): Promise<Map<string, WikiDesc>> {
  const out = new Map<string, WikiDesc>();
  // 최대 60개(3배치)만 조회 — 서버리스 시간예산 보호
  const uniq = [...new Set(titles)].filter(Boolean).slice(0, 60);

  // 원제목 → { en 요약, description, 한국어판 제목 }
  interface EnRow {
    en?: string;
    description?: string;
    koTitle?: string;
  }
  const enByOrig = new Map<string, EnRow>();
  const koTitles = new Set<string>();

  // 배치를 병렬로 — 순차 조회는 서버리스 시간예산을 넘겨 한국어 단계까지 못 가게 한다.
  const chunks: string[][] = [];
  for (let i = 0; i < uniq.length; i += 20) chunks.push(uniq.slice(i, i + 20));

  await Promise.all(
    chunks.map(async (chunk) => {
      try {
        // ⚠️ lllimit 은 '쿼리 전체'의 langlinks 총 개수 상한이다(문서당 아님).
        // lllimit=1 이면 20개 중 1개만 한국어 링크를 받아 나머지가 영어로 폴백된다 → max 필수.
        const url =
          `https://en.wikipedia.org/w/api.php?action=query&format=json&redirects=1` +
          `&prop=extracts|description|langlinks&lllang=ko&lllimit=max` +
          `&exintro=1&explaintext=1&exlimit=max` +
          `&titles=${encodeURIComponent(chunk.join("|"))}`;
        const data = await fetchJson<WikiQueryResp>(url, { timeoutMs: 6_000 });
        const alias = new Map<string, string>();
        for (const n of data.query?.normalized ?? []) alias.set(n.from, n.to);
        for (const r of data.query?.redirects ?? []) alias.set(r.from, r.to);
        const byTitle = new Map<string, EnRow>();
        for (const p of Object.values(data.query?.pages ?? {})) {
          if (p.missing !== undefined) continue;
          const koTitle = p.langlinks?.find((l) => l.lang === "ko")?.["*"];
          byTitle.set(p.title, {
            ...(p.extract ? { en: truncate(p.extract) } : {}),
            ...(p.description ? { description: p.description } : {}),
            ...(koTitle ? { koTitle } : {}),
          });
          if (koTitle) koTitles.add(koTitle);
        }
        for (const orig of chunk) {
          const finalTitle = resolveAlias(orig, alias);
          const row = byTitle.get(finalTitle) ?? byTitle.get(orig);
          if (row) enByOrig.set(orig, row);
        }
      } catch {
        // 조회 실패는 무시(사유가 없을 뿐)
      }
    }),
  );

  // 한국어 위키백과에서 요약을 배치 조회
  const koExtract = await fetchKoreanExtracts([...koTitles]);

  // 조립: 한국어 요약이 있으면 우선, 없으면 영어 요약. 한국어 표제어도 함께 전달.
  for (const [orig, row] of enByOrig.entries()) {
    const ko = row.koTitle ? koExtract.get(row.koTitle) : undefined;
    const extract = ko ?? row.en;
    const desc: WikiDesc = {
      ...(extract ? { extract } : {}),
      ...(row.description ? { description: row.description } : {}),
      ...(row.koTitle ? { title_ko: row.koTitle } : {}),
    };
    if (desc.extract || desc.description || desc.title_ko) out.set(orig, desc);
  }
  return out;
}

/** 한국어 위키백과 제목들 → 한국어 요약 맵(배치 병렬). */
async function fetchKoreanExtracts(koTitles: string[]): Promise<Map<string, string>> {
  const out = new Map<string, string>();
  const uniq = [...new Set(koTitles)].filter(Boolean).slice(0, 60);
  const chunks: string[][] = [];
  for (let i = 0; i < uniq.length; i += 20) chunks.push(uniq.slice(i, i + 20));
  await Promise.all(
    chunks.map(async (chunk) => {
    try {
      const url =
        `https://ko.wikipedia.org/w/api.php?action=query&format=json&redirects=1` +
        `&prop=extracts&exintro=1&explaintext=1&exlimit=max` +
        `&titles=${encodeURIComponent(chunk.join("|"))}`;
      const data = await fetchJson<WikiQueryResp>(url, { timeoutMs: 6_000 });
      const alias = new Map<string, string>();
      for (const n of data.query?.normalized ?? []) alias.set(n.from, n.to);
      for (const r of data.query?.redirects ?? []) alias.set(r.from, r.to);
      const byTitle = new Map<string, string>();
      for (const p of Object.values(data.query?.pages ?? {})) {
        if (p.missing !== undefined || !p.extract) continue;
        byTitle.set(p.title, truncate(p.extract));
      }
      for (const orig of chunk) {
        const finalTitle = resolveAlias(orig, alias);
        const ex = byTitle.get(finalTitle) ?? byTitle.get(orig);
        if (ex) out.set(orig, ex);
      }
    } catch {
      // 한국어 조회 실패 → 해당 항목은 영어 폴백
    }
    }),
  );
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
  const lastKoDot = cut.lastIndexOf("다. ");
  const stop = Math.max(lastDot, lastKoDot);
  return (stop > 60 ? cut.slice(0, stop + 1) : cut) + "…";
}
