# TripVerify — 검증형 여행계획 생성 앱

다른 여행 앱은 "그럴듯한" 일정을 준다. TripVerify 는 **검증되지 않은 정보를 아예 보여주지 않는다.**
사용자에게 노출되는 모든 사실 정보(FACT)는 독립 출처 3곳 이상에서 3중 교차검증을 통과해야 하며,
출처 URL·조회시각·근거 없이는 UI 에 렌더링되지 않는다.

## 절대 원칙 (§0)
1. 환각 금지 — 실제로 조회한 값만.
2. 3중 교차검증 — 독립 출처 3곳 이상. 못 채우면 `confidence: "low"`.
3. 출처 필수 — 모든 FACT 에 `source_url` / `source_name` / `retrieved_at`.
4. 모르면 모른다 — 빈 값은 `null` + `unverified_reason`.

## 실행
```bash
pnpm install
pnpm test          # 코어(스키마·팩토리·판정) 단위 테스트
pnpm dev           # http://localhost:3000, /api/health 로 Phase 0 상태 확인
```
API 키가 하나도 없어도 폴백 소스(Open-Meteo / OSM·Overpass / OSRM / exchangerate.host)로 동작한다.
`.env.example` 을 `.env.local` 로 복사해 키를 넣으면 정확도 높은 소스로 업그레이드된다.

## 아키텍처
- `src/core/` — 프레임워크 독립 순수 로직: `VerifiedFact` 타입, Zod 스키마, 검증 프로토콜, 팩토리.
- `src/db/` — drizzle + SQLite. `audit_log`(검증 감사 로그), `fact_cache`(TTL 캐시).
- `.claude/agents/` — 도메인별 수집 서브에이전트 + verifier + planner (§2).
- `src/app/` — Next.js App Router UI (Phase 7).

## 개발 단계 (전체 완료)
- **Phase 0**: 리포 구조, `.env.example`, `VerifiedFact` 타입/스키마, 감사 로그, 헬스체크.
- **Phase 1**: 3중 검증 프로토콜 코어(verifier) + 단위 테스트.
- **Phase 2**: currency/weather 에이전트(키불필요 소스) + 프록시 HTTP.
- **Phase 3**: poi/food 에이전트 + 캐시 계층(도메인별 TTL, 감사 로그).
- **Phase 4**: route 에이전트 + 클러스터링/2-opt 동선 최적화.
- **Phase 5**: flight/logistics 에이전트.
- **Phase 6**: planner + 파이프라인 오케스트레이션 + `/api/plan`.
- **Phase 7**: UI 전체(타임라인·출처패널·지도·예산·날씨·검증리포트).
- **Phase 8**: E2E(Playwright) + 레이트리밋 + 에러 핸들링 + 배포 설정.

## 테스트
```bash
pnpm test        # 71개 단위/통합 (검증·에이전트·캐시·최적화·조립·파이프라인·레이트리밋)
pnpm test:e2e    # Playwright 3개 (UI 흐름 + API 422/health)
pnpm typecheck   # tsc --noEmit
pnpm build       # next build (standalone)
```

## 배포
- Docker: `docker build -t tripverify . && docker run -p 3000:3000 -v tv:/data tripverify`
- CI: `.github/workflows/tripverify-ci.yml` (typecheck→test→build, apps/tripverify 변경 시).
- 운영 DB 는 `DATABASE_URL` 로 Postgres 전환(현재 개발은 SQLite).

## 무료 오프라인 계층 (네트워크 없이 동작)
외부 API 가 전혀 없어도 아래는 **번들된 무료 데이터셋**(npm)으로 동작한다. 전부 MIT/GeoNames(CC-BY):
- **지오코딩**(도시→좌표/국가/통화코드): `all-the-cities`(GeoNames, 13.5만 도시)
- **공휴일**: `date-holidays`(공식 규칙 기반, 온라인 소스와 합치면 독립 3소스 교차검증)
- **통화 코드**: `country-to-currency`

→ 네트워크가 막혀 있어도 지도 중심·도시 좌표·도시 간 이동방법·예산(추정)·공휴일이 나온다.
온라인일 때는 이 오프라인 소스가 **추가 독립 출처**로 작용해 신뢰도를 끌어올린다.

## 전체 기능을 '무료로' 켜는 법 (환율·날씨·POI)
환율(변동)·날씨·POI 는 본질적으로 실시간 조회가 필요하다. 앱은 이미 **키가 필요 없는 무료
소스만** 쓴다(Open-Meteo · OSM/Overpass · OSRM · frankfurter · Nager.Date). 따라서:

1. **로컬 실행** — 개인 PC 에서 `pnpm dev` 하면 위 무료 API 로 즉시 전체 동작(비용 0).
2. **Vercel 무료 배포** — 무료 티어에 배포하면 서버에서 위 API 를 호출해 전체 동작.
3. **이 환경의 네트워크 정책 열기** — Claude Code on the web 의 환경 설정에서 아웃바운드를
   허용하는 네트워크 정책을 선택(또는 해당 도메인 허용)한다. 현재 이 샌드박스는 조직 egress
   정책이 모든 외부 API(공개 CDN 포함)를 프록시에서 403 으로 차단한다 — 이는 보안 통제이며
   앱이 우회하지 않는다(프록시 README 지침: 정책 거부는 우회 금지, 관리자에게 보고).

> 즉, **추가 비용이나 유료 키 없이** 전체 기능을 쓰는 정식 경로는 "네트워크가 열린 곳에서
> 실행"이며, 앱의 소스 구성 자체가 이미 100% 무료·무키다. 이 사실 자체가 검증 로직으로
> 보장되고, 값을 지어내지 않는다(§0).

## 검증 프로토콜 (§3)
| agree_count | 편차 | confidence | UI |
|---|---|---|---|
| ≥3 | ≤ tolerance | 🟢 high | 정상 표기 |
| 2 | — | 🟡 medium | ⚠ 배지 + 출처 병기 |
| 그 외 | — | 🔴 low | 값 숨김, "확인 필요"만 |

불일치는 다수결이 아니라 출처 등급 우선(공식 > 정부·관광청 > 플랫폼 > 커뮤니티)으로 채택하고,
미채택 값은 `conflicting_values[]` 에 보관한다.
