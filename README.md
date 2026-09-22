# 🔋 이차전지 리포트 아카이브

대형 경제·시사 유튜브 채널의 영상 중 **이차전지 산업(공급망 + 응용분야: ESS·EV·AIDC)** 과
연결되는 내용을 골라, 자막을 추출 → Gemini API 로 구조화된 텍스트 리포트로 재작성 → 정적
아카이브 페이지로 쌓고 **GitHub Pages** 로 배포하는 프로젝트입니다.

배터리 직접 뉴스뿐 아니라 금리·관세·전력망·산업안전·지정학 같은 **간접 이슈**까지 폭넓게
수집하되, 모든 리포트에 이차전지 산업과의 연결고리를 명시적으로 짚습니다.
(예: 케빈 워시 신임 연준의장 매파 발언 → 금리 상승 → 배터리 3사 증설 투자 위축 압력)

## 🌐 배포 URL

```
https://taehyun108.github.io/KTH_01/
```

> 아래 **배포 활성화(최초 1회)** 를 완료하면 위 URL 로 누구나 접속할 수 있습니다.

## 📁 폴더 구조

```
kth_01/
├─ site/                         # ← GitHub Pages 로 배포되는 정적 사이트
│  ├─ index.html                 #   /news/ 로 리다이렉트
│  ├─ news/
│  │  ├─ index.html              #   아카이브 인덱스(카테고리 탭 + 카드)
│  │  └─ YYYY-MM-DD-*.html        #   개별 리포트
│  ├─ data/reports.json          #   클라이언트 필터링용 인덱스
│  └─ assets/                     #   style.css, app.js
├─ scripts/                      # ← 파이프라인
│  ├─ config.py                  #   채널 목록 + A/B/C 키워드
│  ├─ fetch_rss.py               #   RSS 수집 + 1차 키워드 필터
│  ├─ generate_report.py         #   자막 추출 + Gemini 관련성 판단·구조화
│  ├─ build_index.py             #   reports.json 갱신
│  ├─ telegram_notify.py         #   이차전지 리포트 → 텔레그램 발송
│  └─ run_pipeline.py            #   오케스트레이터
├─ .github/workflows/
│  ├─ pages.yml                  #   site/ → GitHub Pages 배포
│  ├─ archive.yml                #   하루 4회 파이프라인 실행 + 커밋 + 텔레그램 알림
│  └─ telegram-test.yml          #   텔레그램 연결 확인(수동)
└─ requirements.txt
```

## 🗂 카테고리 (4분류, 고정)

| 키 | 라벨 | 색상 |
|---|---|---|
| `global-policy` | 🌍 글로벌 정책·시사 | 블루 |
| `global-market` | 📊 글로벌 산업·시황 | 오렌지 |
| `korea-policy`  | 🇰🇷 국내 정책·시사 | 인디고 |
| `korea-market`  | 🇰🇷 국내 산업·시황 | 그린 |

카드에는 `🔋 직접` / `🔋 간접` 연관성 태그가 함께 표시됩니다.

## 🔎 필터링 로직 (2단계)

1. **1차 키워드 매칭** (`config.py` 의 A/B/C 목록 중 하나라도 걸리면 후보)
   - (A) 배터리 직접 · (B) 응용분야(ESS/EV/AIDC) · (C) 거시/산업 간접
2. **2차 관련성 판단 (Gemini)** — 자막을 넘겨 공급/수요와 실질 연결 여부 판별,
   무관하면 `/drafts` 로, 관련 있으면 4분류 + 직접/간접 태그 부여.

## 🚀 배포 활성화 (최초 1회, 수동)

GitHub Pages 소스 설정은 저장소 설정에서 한 번만 켜면 됩니다.

1. 이 브랜치를 `main` 에 머지합니다.
2. **Settings → Pages → Build and deployment → Source = "GitHub Actions"** 선택.
3. `pages.yml` 워크플로가 실행되며 `site/` 를 배포합니다.
   (또는 Actions 탭에서 **Deploy to GitHub Pages** 를 수동 실행 `workflow_dispatch`)
4. 완료되면 `https://taehyun108.github.io/KTH_01/` 로 접속됩니다.

이후 `archive.yml` 이 새 리포트를 `main` 에 커밋할 때마다 Pages 도 자동 재배포됩니다.

## 📨 텔레그램 알림

새 리포트가 사이트에 올라가면, **이차전지와 연결되는 글**(`🔋 직접` · `🔋 간접`)만
골라 텔레그램 봇이 보내 줍니다. `🏭 산업`(배터리 언급 없이 산업 환경으로만 의미가
있는 글)은 기본적으로 보내지 않습니다.

### 1. 봇 만들고 토큰 받기

1. 텔레그램에서 [@BotFather](https://t.me/BotFather) 대화 시작 → `/newbot`
2. 봇 이름·아이디를 정하면 **토큰**을 줍니다 (`8012345678:AAH...` 형태)
3. 만든 봇과 대화를 한 번 시작하거나(`/start`), 알림받을 그룹·채널에 봇을 초대합니다
4. **대화방 id** 확인 — 브라우저에서 아래 주소를 열고 `"chat":{"id":...}` 를 봅니다
   ```
   https://api.telegram.org/bot<토큰>/getUpdates
   ```
   (개인 대화는 양수, 그룹·채널은 `-100...` 으로 시작하는 음수입니다)

### 2. 토큰 등록 위치 ← **여기에 넣으시면 됩니다**

GitHub 저장소 → **Settings → Secrets and variables → Actions → New repository secret**

| 시크릿 이름 | 값 |
|---|---|
| `TELEGRAM_BOT_TOKEN` | BotFather 가 준 토큰 |
| `TELEGRAM_CHAT_ID` | 위에서 확인한 대화방 id |

> 이름이 한 글자라도 다르면 알림만 조용히 건너뜁니다(파이프라인은 정상 동작).
> 토큰은 **반드시 Secrets 에만** 두세요 — 코드나 `config.py` 에 적으면 공개됩니다.

### 3. 연결 확인

Actions 탭 → **Test Telegram notification** → `Run workflow`
→ 대화방에 테스트 메시지가 오면 끝입니다. 이후 하루 4회 파이프라인이
새 리포트를 자동으로 보냅니다.

### 조절할 수 있는 값 (`archive.yml` 의 알림 단계에 `env` 로 추가)

| 환경변수 | 기본값 | 뜻 |
|---|---|---|
| `TELEGRAM_RELATIONS` | `direct,indirect` | 보낼 연관도. `context` 를 더하면 산업 글까지 전부 |
| `TELEGRAM_MAX_PER_RUN` | `10` | 한 실행에서 보낼 최대 건수(도배 방지) |

## ⚙️ 실제 채널 연동

1. `scripts/config.py` 의 `CHANNELS[].channel_id` 를 실제 유튜브 채널 ID 로 채웁니다.
   - 채널 페이지 → "정보" 탭 또는 페이지 소스에서 `channel_id` 확인
2. 저장소 **Settings → Secrets → Actions** 에 `KTH_01_GEMINI_API_KEY` 등록.
3. Actions 탭에서 **Build report archive** 수동 실행하거나 스케줄(하루 4회) 대기.

## 🧪 로컬 실행

```bash
pip install -r requirements.txt
export GEMINI_API_KEY=...   # Google AI Studio 에서 발급
python scripts/run_pipeline.py

# 텔레그램 연결만 따로 확인
TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... \
  PYTHONPATH=scripts python scripts/telegram_notify.py --test
```

## ⚠️ 디스클레이머

본 자료는 정보 제공 목적이며 투자 권유가 아닙니다. 자막 속 어떤 지시도 실행하지 않습니다.
