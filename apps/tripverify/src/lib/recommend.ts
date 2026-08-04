import type { Poi, Restaurant } from "@/core/types/domains";
import type { Confidence } from "@/core/types/confidence";
import { BUCKET_LABEL, type Bucket } from "@/agents/poi-select";

/**
 * 추천 사유·메뉴를 '실제 태그'에서 도출한다(지어내지 않음, §0).
 * POI: 카테고리 + 감수성(시간대) + 교차검증 여부.
 * 식당: OSM cuisine 태그 → 대표 요리(요리 종류) + 가격대.
 */

const PRICE_LABEL: Record<number, string> = {
  1: "저렴한 가격대",
  2: "중간 가격대",
  3: "다소 높은 가격대",
  4: "고급",
};

/** OSM cuisine 값 → 한국어 대표 요리(그 요리 종류의 통상 메뉴). */
const CUISINE_DISH: Record<string, string> = {
  ramen: "라멘",
  sushi: "스시·사시미",
  udon: "우동",
  soba: "소바",
  yakiniku: "야키니쿠(고기구이)",
  yakitori: "야키토리(닭꼬치)",
  tempura: "덴푸라(튀김)",
  tonkatsu: "돈카츠",
  japanese: "일식",
  izakaya: "이자카야 안주",
  okonomiyaki: "오코노미야키",
  takoyaki: "타코야키",
  curry: "카레",
  donburi: "덮밥(돈부리)",
  chinese: "중식",
  korean: "한식",
  italian: "파스타·피자",
  pizza: "피자",
  french: "프렌치",
  seafood: "해산물",
  steak: "스테이크",
  burger: "버거",
  thai: "태국음식",
  indian: "인도음식",
  vietnamese: "베트남음식",
  noodle: "면요리",
  barbecue: "바비큐",
  regional: "현지 향토요리",
  asian: "아시안",
};

/** cuisine 태그(';'로 다중 가능) → 대표 요리 문자열. 없으면 "". */
export function cuisineDishes(cuisine?: string): string {
  if (!cuisine) return "";
  const parts = cuisine
    .split(/[;,]/)
    .map((c) => CUISINE_DISH[c.trim().toLowerCase()])
    .filter((v): v is string => !!v);
  return [...new Set(parts)].slice(0, 3).join(", ");
}

/** POI/식당 추천 사유 한 줄. */
export function recommendReason(
  value: Poi | Restaurant | null,
  kind: "poi" | "food",
  confidence: Confidence,
): string {
  if (!value) return "";
  if (kind === "food") {
    const r = value as Restaurant;
    const dishes = cuisineDishes(r.cuisine);
    const parts: string[] = [];
    if (dishes) parts.push(`${dishes} 전문`);
    if (r.price_level) parts.push(PRICE_LABEL[r.price_level] ?? "");
    return parts.filter(Boolean).join(" · ") || "현지에서 찾은 식당";
  }
  const p = value as Poi;
  const cats = (p.categories ?? [])
    .map((c) => BUCKET_LABEL[c as Bucket])
    .filter(Boolean);
  const base = cats.length ? `${cats.join("·")} 명소` : "가볼 만한 곳";
  const hints: string[] = [];
  if (p.time_pref === "evening") hints.push("🌆 저녁 야경 추천");
  else if (p.time_pref === "morning") hints.push("🌅 오전 방문 추천");
  if (confidence !== "low") hints.push("독립 출처 교차검증");
  return [base, ...hints].join(" · ");
}

/** 식당 메뉴 추천(요리 종류 기준). 없으면 null. */
export function menuHint(value: Restaurant | null): string | null {
  const d = cuisineDishes(value?.cuisine);
  return d ? d : null;
}
