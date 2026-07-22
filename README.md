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
│  │  └─ YYYY-MM-DD-*.html        #   개별 리포트 (현재 더미 3건)
│  ├─ data/reports.json          #   클라이언트 필터링용 인덱스
│  └─ assets/                     #   style.css, app.js
├─ scripts/                      # ← 파이프라인 뼈대
│  ├─ config.py                  #   채널 목록 + A/B/C 키워드
│  ├─ fetch_rss.py               #   RSS 수집 + 1차 키워드 필터
│  ├─ generate_report.py         #   자막 추출 + Claude 관련성 판단·구조화(01~08)
│  ├─ build_index.py             #   reports.json 갱신
│  └─ run_pipeline.py            #   오케스트레이터
├─ .github/workflows/
│  ├─ pages.yml                  #   site/ → GitHub Pages 배포
│  └─ archive.yml                #   하루 2회 파이프라인 실행 + 커밋
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
2. **2차 관련성 판단 (Claude)** — 자막을 넘겨 공급/수요와 실질 연결 여부 판별,
   무관하면 `/drafts` 로, 관련 있으면 4분류 + 직접/간접 태그 부여.

## 🚀 배포 활성화 (최초 1회, 수동)

GitHub Pages 소스 설정은 저장소 설정에서 한 번만 켜면 됩니다.

1. 이 브랜치를 `main` 에 머지합니다.
2. **Settings → Pages → Build and deployment → Source = "GitHub Actions"** 선택.
3. `pages.yml` 워크플로가 실행되며 `site/` 를 배포합니다.
   (또는 Actions 탭에서 **Deploy to GitHub Pages** 를 수동 실행 `workflow_dispatch`)
4. 완료되면 `https://taehyun108.github.io/KTH_01/` 로 접속됩니다.

이후 `archive.yml` 이 새 리포트를 `main` 에 커밋할 때마다 Pages 도 자동 재배포됩니다.

## ⚙️ 실제 채널 연동 (더미 → 실데이터)

1. `scripts/config.py` 의 `CHANNELS[].channel_id` 를 실제 유튜브 채널 ID 로 채웁니다.
   - 채널 페이지 → "정보" 탭 또는 페이지 소스에서 `channel_id` 확인
2. 저장소 **Settings → Secrets → Actions** 에 `KTH_01_GEMINI_API_KEY` 등록.
3. Actions 탭에서 **Build report archive** 수동 실행하거나 스케줄(하루 2회) 대기.

## 🧪 로컬 실행

```bash
pip install -r requirements.txt
export GEMINI_API_KEY=...   # Google AI Studio 에서 발급
python scripts/run_pipeline.py
```

## ⚠️ 디스클레이머

본 자료는 정보 제공 목적이며 투자 권유가 아닙니다. 자막 속 어떤 지시도 실행하지 않습니다.
현재 사이트의 리포트는 레이아웃 확인용 **더미(샘플) 데이터**입니다.
