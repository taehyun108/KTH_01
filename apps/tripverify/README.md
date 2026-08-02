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

## ⚠ 이 실행 환경에서의 동작(중요)
현재 샌드박스의 **네트워크 정책이 외부 데이터 API(Open-Meteo/OSM/OSRM/환율 등)를
프록시 게이트웨이에서 403 으로 차단**한다. 따라서 이 환경에서 `/api/plan` 을 호출하면
앱은 **거짓 데이터를 지어내지 않고**(§0-1) 빈 일정 + 안내(notes)로 정직하게 응답한다(§0-4).
검증·최적화·조립 등 모든 로직은 결정론적 단위/통합 테스트(주입식 소스)로 검증되며,
**네트워크가 허용된 환경에서는 동일 코드가 실제 검증된 일정을 생성**한다. 합성 데이터는
테스트 전용이며 UI 로 전달되지 않는다.

## 검증 프로토콜 (§3)
| agree_count | 편차 | confidence | UI |
|---|---|---|---|
| ≥3 | ≤ tolerance | 🟢 high | 정상 표기 |
| 2 | — | 🟡 medium | ⚠ 배지 + 출처 병기 |
| 그 외 | — | 🔴 low | 값 숨김, "확인 필요"만 |

불일치는 다수결이 아니라 출처 등급 우선(공식 > 정부·관광청 > 플랫폼 > 커뮤니티)으로 채택하고,
미채택 값은 `conflicting_values[]` 에 보관한다.
