# TripVerify 무료 배포 가이드

이 앱은 **유료 키 없이** 100% 무료로 배포·구동된다. 사용하는 데이터 소스가 전부
키 불필요(Open-Meteo · OSM/Overpass · OSRM · frankfurter · Nager.Date)이고,
네트워크가 없을 때도 번들된 무료 데이터(GeoNames · date-holidays)로 부분 동작한다.

리포 구조상 앱은 서브폴더 `apps/tripverify` 에 있다. 배포 시 **Root Directory 를
`apps/tripverify` 로 지정**하는 것이 핵심이다.

---

## A. Vercel (권장, 무료 Hobby)

1. https://vercel.com 에 GitHub 계정으로 로그인(무료).
2. **Add New → Project → Import** 에서 이 리포(`taehyun108/kth_01`)를 선택.
3. **Root Directory** 를 `apps/tripverify` 로 설정(중요). Framework 는 Next.js 자동 감지.
4. Build/Install 명령은 `vercel.json` 이 지정하므로 그대로 두면 된다.
   - Install: `pnpm install --frozen-lockfile`
   - Build: `pnpm build`
5. 환경변수는 **아무것도 필요 없다**(전부 무료·무키). 선택적으로 정확도/한도를
   올리고 싶으면 `.env.example` 의 키를 프로젝트 환경변수에 추가.
6. **Deploy** 클릭 → 1~2분 후 `https://<프로젝트>.vercel.app` 발급.

동작 특성:
- `/api/plan` 이 서버에서 무료 API 를 호출해 **검증된 다중 도시 일정·이동·예산**을 생성.
- SQLite 캐시/감사 로그는 서버리스 `/tmp`(휘발성)에 기록되며, 사용 불가 시 자동
  비활성화된다(앱 동작에는 영향 없음).
- `/api/plan` 함수 최대 실행시간은 60초(Hobby 상한)로 설정됨.

> CLI 로도 가능: `npm i -g vercel && cd apps/tripverify && vercel`(로그인 후 프롬프트에서
> Root 확인). 브라우저 Import 방식이 가장 간단하다.

---

## B. 대안 (모두 무료 티어 존재)

- **Netlify**: Base directory `apps/tripverify`, `@netlify/plugin-nextjs` 자동 적용.
- **Render / Railway**: Node 웹서비스, Root `apps/tripverify`, `pnpm build` → `pnpm start`.
- **Cloudflare Pages**: Next 지원(일부 노드 API 제약). SQLite 캐시는 비활성화됨(무해).
- **Docker(자가 호스팅)**: 리포의 `Dockerfile`(standalone) 사용.
  `docker build -t tripverify . && docker run -p 3000:3000 -v tv:/data tripverify`

---

## C. 로컬 실행(가장 빠른 무료 검증)

```bash
cd apps/tripverify
pnpm install
pnpm dev      # http://localhost:3000
```
개인 PC 는 아웃바운드가 열려 있으므로 위 무료 API 로 **즉시 전체 기능**이 동작한다.

---

## 참고: 이 Claude 실행 환경에서 전체 동작이 안 되는 이유
조직 egress 정책이 외부 API(공개 CDN 포함)를 프록시에서 403 으로 차단하기 때문이다.
이는 보안 통제이며 앱이 우회하지 않는다. 위 A/B/C 중 아무 곳(전부 무료)에 올리면
네트워크가 열려 전체 기능이 동작한다.
