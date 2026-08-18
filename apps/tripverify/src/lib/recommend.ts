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

/**
 * 요리 종류 → 한국인 여행자가 즐겨 찾는 대표 '메뉴' 예시(그 종류의 통상 메뉴).
 * 특정 식당의 실제 메뉴가 아니라 '이런 요리집의 대표 메뉴'라는 일반 안내(§0 — 지어내지 않음).
 */
const CUISINE_POPULAR_MENU: Record<string, string[]> = {
  ramen: ["돈코츠 라멘", "차슈멘", "교자(군만두)"],
  sushi: ["오마카세", "모둠초밥", "우니(성게)·연어초밥"],
  udon: ["붓카케 우동", "튀김(텐푸라) 우동", "카레 우동"],
  soba: ["자루소바(냉)", "텐푸라 소바"],
  yakiniku: ["와규 등심·안창살", "갈비", "우설(탄시오)"],
  yakitori: ["닭꼬치 모둠", "츠쿠네(닭완자)", "네기마"],
  tempura: ["새우튀김", "모둠 덴푸라", "텐동(튀김덮밥)"],
  tonkatsu: ["로스카츠", "히레카츠", "카츠동"],
  japanese: ["정식(테이쇼쿠)", "사시미 모둠", "덴푸라"],
  izakaya: ["카라아게(닭튀김)", "에다마메", "하이볼·사케 안주"],
  okonomiyaki: ["오코노미야키", "야키소바", "몬자야키"],
  takoyaki: ["타코야키(문어빵)"],
  curry: ["카츠카레", "일본식 카레라이스"],
  donburi: ["규동(소고기덮밥)", "가이센동(해산물덮밥)", "텐동"],
  chinese: ["딤섬", "마파두부", "볶음밥·꿔바로우"],
  dim_sum: ["하가우(새우만두)", "샤오마이", "차슈바오"],
  shanghainese: ["샤오롱바오", "훠궈", "동파육"],
  cantonese: ["딤섬", "완탕면", "차슈"],
  korean: ["현지 한식"],
  italian: ["파스타", "화덕피자", "리조또"],
  pizza: ["마르게리타", "나폴리 피자"],
  french: ["코스요리", "스테이크·푸아그라", "에스카르고"],
  seafood: ["해산물 모둠", "굴·조개", "게·랍스터"],
  steak: ["스테이크", "티본·립아이"],
  burger: ["수제버거", "치즈버거"],
  thai: ["팟타이", "똠얌꿍", "그린커리"],
  indian: ["버터치킨 커리", "탄두리", "난·비리야니"],
  vietnamese: ["쌀국수(포)", "반미", "분짜"],
  noodle: ["대표 면요리"],
  barbecue: ["바비큐 플래터", "립"],
  spanish: ["파에야", "타파스", "감바스 알 아히요"],
  tapas: ["타파스 모둠", "하몽", "감바스"],
  paella: ["해산물 파에야", "발렌시아 파에야"],
  catalan: ["파에야", "판 콘 토마테", "크레마 카탈라나"],
  mediterranean: ["그릴 해산물", "올리브·치즈 플래터"],
  portuguese: ["바칼라우(대구요리)", "에그타르트", "그릴 정어리"],
  mexican: ["타코", "부리토", "과카몰리·나초"],
  german: ["학센(슈바인스학세)", "소시지 플래터", "슈니첼"],
  turkish: ["케밥", "쾨프테", "바클라바"],
  greek: ["수블라키", "무사카", "그릭 샐러드·기로스"],
  american: ["버거", "스테이크", "바비큐"],
};

/**
 * 요리 종류 → 한국인 즐겨찾는 대표 메뉴 문자열(최대 3개). 없으면 "".
 * 여러 cuisine 태그가 있으면 첫 매칭 종류의 메뉴를 사용한다.
 */
export function popularMenu(cuisine?: string): string {
  if (!cuisine) return "";
  for (const c of cuisine.split(/[;,]/)) {
    const dishes = CUISINE_POPULAR_MENU[c.trim().toLowerCase()];
    if (dishes && dishes.length) return dishes.slice(0, 3).join(", ");
  }
  return "";
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
  const hints: string[] = [];
  if (p.all_day) hints.push("🎢 종일 코스");
  if (p.time_pref === "evening") hints.push("🌆 저녁 야경 추천");
  else if (p.time_pref === "morning") hints.push("🌅 오전 방문 추천");
  if (confidence !== "low") hints.push("독립 출처 교차검증");

  // Wikipedia 설명이 있으면 그것을 '왜 추천하는지'의 근거로 사용(§0 실제 출처)
  if (p.description) {
    const tag = cats.length ? `[${cats.join("·")}] ` : "";
    return `${tag}${p.description}${hints.length ? ` · ${hints.join(" · ")}` : ""}`;
  }
  const base = cats.length ? `${cats.join("·")} 명소` : "가볼 만한 곳";
  return [base, ...hints].join(" · ");
}

/**
 * 식당 추천 메뉴(한국인 여행자 기준의 대표 메뉴 예시). 없으면 null.
 * OSM cuisine 태그가 있으면 그 요리 종류의 대표 메뉴를, 없으면 null.
 */
export function menuHint(value: Restaurant | null): string | null {
  const menu = popularMenu(value?.cuisine);
  if (menu) return menu;
  // 대표 메뉴 매핑이 없는 종류는 요리 종류라도 안내
  const d = cuisineDishes(value?.cuisine);
  return d ? d : null;
}

/** 도시/지역명 → 그 지역 명물(현지 대표 음식). cuisine 태그가 없을 때의 폴백 안내. */
const LOCALE_SIGNATURE: [RegExp, string][] = [
  [/오사카|osaka/i, "타코야키, 오코노미야키, 쿠시카츠"],
  [/교토|kyoto/i, "유도후(두부요리), 니신소바, 가이세키"],
  [/도쿄|tokyo/i, "스시, 몬자야키, 텐동"],
  [/후쿠오카|fukuoka|하카타|hakata/i, "하카타 라멘, 모츠나베, 명란(멘타이코)"],
  [/삿포로|sapporo|홋카이도|hokkaido/i, "미소 라멘, 징기스칸(양고기), 성게·게요리"],
  [/나고야|nagoya/i, "히츠마부시(장어), 미소카츠, 데바사키(닭날개)"],
  [/오키나와|okinawa/i, "오키나와 소바, 타코라이스, 아구(흑돼지)"],
  [/상하이|shanghai/i, "샤오롱바오, 훠궈, 동파육"],
  [/베이징|beijing/i, "베이징덕(오리구이), 훠궈, 자장면"],
  [/타이베이|taipei|대만|taiwan/i, "샤오롱바오, 우육면, 루러우판, 버블티"],
  [/방콕|bangkok|태국|thailand/i, "팟타이, 똠얌꿍, 카오소이, 망고밥"],
  [/바르셀로나|barcelona|스페인|spain/i, "파에야, 타파스, 하몽, 감바스"],
  [/리스본|lisbon|lisboa|포르투|porto|포르투갈|portugal/i, "바칼라우(대구요리), 파스텔 드 나타(에그타르트), 그릴 정어리"],
  [/파리|paris|프랑스|france/i, "스테이크 프리트, 에스카르고, 크레페"],
  [/로마|rome|이탈리아|ital/i, "파스타(까르보나라), 화덕피자, 젤라토"],
  [/부산|busan/i, "돼지국밥, 밀면, 회·해산물"],
  [/제주|jeju/i, "흑돼지 구이, 고기국수, 갈치·전복요리"],
  [/서울|seoul/i, "한정식, 삼겹살, 냉면"],
];

/** cuisine 태그가 없는 식당의 지역 명물 안내(한국인 여행자 기준). 없으면 null. */
export function localeMenu(city?: string): string | null {
  if (!city) return null;
  for (const [re, dishes] of LOCALE_SIGNATURE) if (dishes && re.test(city)) return dishes;
  return null;
}
