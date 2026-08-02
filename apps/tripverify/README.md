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

## 개발 단계
- **Phase 0 (완료)**: 리포 구조, `.env.example`, `VerifiedFact` 타입/스키마, 감사 로그 테이블, 헬스체크.
- Phase 1: verifier-agent 코어 + 검증 프로토콜 단위 테스트.
- Phase 2~8: 수집 에이전트 → 최적화 → planner → UI → E2E.

## 검증 프로토콜 (§3)
| agree_count | 편차 | confidence | UI |
|---|---|---|---|
| ≥3 | ≤ tolerance | 🟢 high | 정상 표기 |
| 2 | — | 🟡 medium | ⚠ 배지 + 출처 병기 |
| 그 외 | — | 🔴 low | 값 숨김, "확인 필요"만 |

불일치는 다수결이 아니라 출처 등급 우선(공식 > 정부·관광청 > 플랫폼 > 커뮤니티)으로 채택하고,
미채택 값은 `conflicting_values[]` 에 보관한다.
