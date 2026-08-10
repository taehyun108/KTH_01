"""
파이프라인 공용 설정 — 채널 목록, 키워드, 경로.

채널 ID(channel_id)는 유튜브 채널 페이지 → '정보' 탭 또는 페이지 소스에서 확인 후
아래 CHANNELS 의 channel_id 를 채워 넣으세요. (현재는 뼈대용 placeholder)
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# 경로
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
SITE_DIR = ROOT / "site"
NEWS_DIR = SITE_DIR / "news"
DATA_DIR = SITE_DIR / "data"
REPORTS_JSON = DATA_DIR / "reports.json"
DRAFTS_DIR = ROOT / "drafts"          # 애매한 건 수동 확인용

# ---------------------------------------------------------------------------
# RSS 소스 — 대형 경제·시사 채널 (배터리 전문 채널 아님)
#   channel_id 는 유튜브 채널 '정보' 탭 / 페이지 소스에서 확인해 채워 넣을 것.
#   RSS URL 패턴: https://www.youtube.com/feeds/videos.xml?channel_id=<ID>
# ---------------------------------------------------------------------------
CHANNELS = [
    # 국내 경제·시사 채널
    {"name": "삼프로TV",            "channel_id": "UChlv4GSd7OQl3js-jkLOnFA"},
    {"name": "슈카월드",            "channel_id": "UCsJ6RuBiTVWRX156FVbeaGg"},
    {"name": "언더스탠딩",          "channel_id": "UCIUni4ScRp4mqPXsxy62L5w"},
    {"name": "소수몽키",            "channel_id": "UCC3yfxS5qC6PCwDzetUuEWg"},
    {"name": "슈퍼개미 이세무사TV",  "channel_id": "UCowHl0BGalL433P6bCBgeKA"},
    {"name": "손석희의 12시",        "channel_id": "UCSb2WFb8m73erqFmP04Mokw"},
    {"name": "손에 잡히는 경제",      "channel_id": "UCiYbaVEODktcsh09454Grow"},
    # 박종훈의 지식한방 (@kpunch) — 2026-08-09 추가.
    # 채널 id 는 PLAYBOARD 채널 페이지와 youtube.com/channel/<id>/videos('jisik-hanbang')
    # 두 곳에서 교차 확인했다. scripts/check_channels.py 로 실제 응답도 확인할 수 있다.
    {"name": "박종훈의 지식한방",     "channel_id": "UCOB62fKRT7b73X7tRxMuN2g"},
    # 전인구경제연구소는 사용자 요청으로 제외됨.
    # 해외 거시경제·시사 채널 (영어) — 자막/키워드는 영문 처리
    {"name": "Patrick Boyle",       "channel_id": "UCASM0cgfkJxQ1ICmRilfHLw"},
    {"name": "Economics Explained", "channel_id": "UCZ4AMrDcNrfy3X6nsU8-rPg"},
    {"name": "ColdFusion",          "channel_id": "UC4QZ_LsYcvcq7qOsOhpAX4A"},
    {"name": "Money & Macro",       "channel_id": "UCCKpicnIwBP3VPxBAZWDeNA"},
    {"name": "The Plain Bagel",     "channel_id": "UCFCEuCsyWP0YkP3CZ3Mr01Q"},
    {"name": "CNBC International",   "channel_id": "UCo7a6riBFJ3tkeHjvkXPn1g"},
    {"name": "The Wall Street Journal", "channel_id": "UCK7tptUDHh-RYDsdxO1-5QQ"},
]

RSS_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

# ---------------------------------------------------------------------------
# 1차 키워드 매칭 (A/B/C 중 하나라도 걸리면 후보로 픽업)
# ---------------------------------------------------------------------------
KW_DIRECT = [  # (A) 배터리 직접
    "이차전지", "2차전지", "배터리", "셀", "리튬", "니켈", "코발트", "흑연",
    "전고체", "양극재", "음극재", "분리막", "전해질", "LFP", "하드카본",
    "LG에너지솔루션", "삼성SDI", "SK온", "에코프로", "포스코퓨처엠", "엘앤에프", "CATL",
]

KW_APPLICATION = [  # (B) 응용분야(수요처): ESS / EV / AIDC
    # ESS
    "ESS", "에너지저장장치", "BESS", "그리드 스토리지", "전력저장", "ESS 화재",
    "ESS 안전기준", "V2G", "가상발전소", "VPP", "재생에너지 연계",
    # EV
    "전기차", "EV", "xEV", "캐즘", "전기차 캐즘", "완성차", "테슬라",
    "현대차", "기아", "충전인프라", "보조금 폐지", "보조금 축소", "연비규제",
    # AIDC
    "데이터센터", "AIDC", "AI 데이터센터", "전력 병목", "전력 인프라", "변압기",
    "UPS", "백업전원", "전력조달", "PPA", "그리드 접속",
]

KW_TRADE = [  # (C-1) 통상·관세 — '관세'는 한 단어라 채널 상용구에도 흔해 제목 매칭 전용
    "관세", "상호관세", "보편관세", "품목관세", "관세율", "관세 부과", "관세 인상",
    "고율관세", "추가관세", "무역분쟁", "무역전쟁", "통상마찰", "무역협상",
    "수출규제", "수출통제", "수입규제", "반덤핑", "상계관세", "세이프가드",
    "무역확장법", "232조", "301조", "슈퍼 301조", "블랙리스트", "엔티티 리스트",
    "FTA", "자유무역협정", "원산지", "우회수출", "비관세장벽", "수입 쿼터", "수출 쿼터", "수출입 규제",
    "희토류 수출", "핵심광물 통제", "디리스킹", "공급망 재편",
]

KW_KR_POLICY = [  # (C-2) 국내 정책·제도 — 그동안 누락돼 국내정책 리포트가 거의 없었던 영역
    # 조세·재정 지원
    "국내생산세액공제", "생산세액공제", "세액공제", "통합투자세액공제", "조세특례",
    "조세특례제한법", "감세", "증세 논의", "증세안", "세금 인상", "법인세",
    "세제개편", "세제 지원", "보조금",
    "정부 지원금", "추경", "추가경정예산", "예산안", "국가재정", "정책자금", "정책금융",
    # 산업·전략 법제
    "첨단전략산업", "국가첨단전략산업", "국가전략기술", "반도체특별법", "K-칩스법",
    "특별법", "특별회계", "산업정책", "규제완화", "규제혁신", "인허가", "시행령",
    "국무회의", "국정과제", "산업통상자원부", "기획재정부", "중소벤처기업부",
    "산업은행", "수출입은행", "무역보험", "첨단산업기금", "마더팩토리",
    # 에너지·전력 제도
    "전력수급기본계획", "전기요금", "전기료", "산업용 전기", "요금 인상",
    "탄소중립", "배출권", "배출권거래제", "RE100", "재생에너지 의무",
    "원전", "원자력", "송배전", "계통 연계", "전력계통",
    # 안전·인증 제도
    "안전기준", "안전규제", "안전인증", "형식인증", "KC 인증", "화재", "폭발", "안전사고",
    "리콜", "중대재해", "환경규제", "ESG",
]

KW_MACRO = [  # (C-3) 순수 거시 — 금리·물가·환율·증시 전반
    "금리", "기준금리", "연준", "FOMC", "한국은행", "통화정책", "양적긴축",
    "인플레이션", "물가상승", "물가 상승", "소비자물가", "물가안정", "물가 안정",
    "환율", "원달러", "유가", "국채", "채권금리",
    "경기침체", "경기둔화", "고용지표", "GDP", "증시", "코스피", "나스닥",
    "전력망", "정전", "공급망", "지정학", "중국 산업정책",
]

# ---------------------------------------------------------------------------
# 영문 키워드 (해외 채널: Patrick Boyle, Economics Explained, WSJ 등)
#   match_keywords 가 영문 키워드는 '단어 경계'로 매칭하므로 짧은 약어(EV, ESS)도
#   development·business 같은 단어에 오검출되지 않는다.
# ---------------------------------------------------------------------------
KW_EN_DIRECT = [  # (A) 배터리 직접
    "battery", "batteries", "lithium", "nickel", "cobalt", "graphite",
    "solid-state", "cathode", "anode", "gigafactory", "CATL", "LFP", "rare earth",
]
KW_EN_APPLICATION = [  # (B) 응용분야: EV / ESS / AIDC
    "electric vehicle", "electric vehicles", "electric car", "electric cars",
    "EV", "EVs", "Tesla", "BYD", "energy storage", "grid storage", "power grid",
    "data center", "data centre", "data centers", "data centres", "charging",
]
KW_EN_TRADE = [  # (C-1) 통상·관세
    "tariff", "tariffs", "trade war", "trade deal", "trade talks", "export control",
    "export controls", "export ban", "sanctions", "entity list", "anti-dumping",
    "countervailing duty", "safeguard", "Section 232", "Section 301",
    "de-risking", "reshoring", "friendshoring", "rare earth export",
]
KW_EN_POLICY = [  # (C-2) 산업정책·보조금 (해외)
    "Inflation Reduction Act", "IRA", "CHIPS Act", "subsidy", "subsidies",
    "tax credit", "tax credits", "45X", "industrial policy", "stimulus",
    "carbon tax", "emissions trading", "clean energy plan", "permitting reform",
]
KW_EN_MACRO = [  # (C-3) 순수 거시
    "interest rate", "interest rates", "Federal Reserve", "rate cut", "rate hike",
    "inflation", "recession", "supply chain", "supply chains",
    "semiconductor", "semiconductors", "geopolitics", "renewable energy",
    "energy transition", "oil price", "bond market", "China economy",
]

def _dedup(*groups: list[str]) -> list[str]:
    """여러 키워드 묶음을 순서를 지키며 합치고 중복을 제거한다.
    (중복이 남으면 같은 키워드가 매칭 결과에 두 번 잡힌다)"""
    seen: set[str] = set()
    out: list[str] = []
    for g in groups:
        for k in g:
            if k not in seen:
                seen.add(k)
                out.append(k)
    return out


ALL_KEYWORDS = _dedup(
    KW_DIRECT, KW_APPLICATION, KW_TRADE, KW_KR_POLICY, KW_MACRO,
    KW_EN_DIRECT, KW_EN_APPLICATION, KW_EN_TRADE, KW_EN_POLICY, KW_EN_MACRO,
)

# ---------------------------------------------------------------------------
# 설명글(description) 매칭 전용 키워드
# ---------------------------------------------------------------------------
# 제목은 그 영상만의 문장이라 ALL_KEYWORDS 를 다 써도 안전하다. 반면 설명글에는
# 채널 고정 소개문·해시태그·광고가 늘 붙어 있어서, '금리'·'전기차'·'관세'처럼 짧고
# 흔한 낱말로 매칭하면 무관한 영상(예술·과학·교육)이 대량으로 딸려 들어온다.
# → 설명글에는 '그 주제를 실제로 다루지 않으면 잘 안 쓰는 구체적 표현'만 허용한다.
_DESC_SAFE_TRADE = [
    "상호관세", "보편관세", "품목관세", "관세율", "관세 부과", "관세 인상",
    "고율관세", "추가관세", "무역분쟁", "무역전쟁", "통상마찰", "무역협상",
    "수출규제", "수출통제", "수입규제", "반덤핑", "상계관세", "세이프가드",
    "무역확장법", "232조", "301조", "엔티티 리스트", "자유무역협정",
    "우회수출", "비관세장벽", "희토류 수출", "핵심광물 통제", "공급망 재편",
]
_DESC_SAFE_KR_POLICY = [
    "국내생산세액공제", "생산세액공제", "세액공제", "통합투자세액공제", "조세특례",
    "조세특례제한법", "세제개편", "세제 지원", "추가경정예산", "정책금융",
    "첨단전략산업", "국가첨단전략산업", "국가전략기술", "반도체특별법", "K-칩스법",
    "규제완화", "규제혁신", "산업통상자원부", "기획재정부", "첨단산업기금",
    "마더팩토리", "전력수급기본계획", "산업용 전기", "배출권거래제", "재생에너지 의무",
    "중대재해", "환경규제", "안전규제", "KC 인증",
]
_DESC_SAFE_EN = [
    "Inflation Reduction Act", "CHIPS Act", "tax credit", "tax credits", "45X",
    "industrial policy", "export control", "export controls", "entity list",
    "anti-dumping", "countervailing duty", "Section 232", "Section 301",
    "trade war", "rare earth export", "energy storage", "grid storage",
    "electric vehicle", "electric vehicles", "gigafactory", "solid-state",
]
SPECIFIC_KEYWORDS = _dedup(
    KW_DIRECT, KW_EN_DIRECT, _DESC_SAFE_TRADE, _DESC_SAFE_KR_POLICY, _DESC_SAFE_EN,
)

# 카테고리 정의 (LLM 분류가 이 중 하나를 반환). macro=거시경제(금리·환율·유가·증시 전반)
CATEGORIES = ["global-policy", "global-market", "korea-policy", "korea-market", "macro"]

# Gemini 모델 (시크릿 KTH_01_GEMINI_API_KEY → 환경변수 GEMINI_API_KEY)
# 실제 사용 모델은 런타임에 generateContent 지원 목록에서 자동 선택되며,
# 아래 값은 목록 조회 실패 시의 최종 폴백입니다.
#   ※ 예전 폴백이던 gemini-2.5-flash 는 이 키로 404('no longer available to
#     new users')가 납니다. 폴백이 곧바로 실패하는 값이면 폴백이 아닙니다.
GEMINI_MODEL = "gemini-flash-lite-latest"

# 모델을 못 박고 싶을 때 쓰는 환경변수. 비어 있으면 자동 선택에 맡깁니다.
# 무료 한도는 모델마다 크게 다르므로(2026-08-10 실측: gemini-3.6-flash 는 하루 20건)
# 코드를 고치지 않고 워크플로에서 바꿔 볼 수 있어야 합니다.
GEMINI_MODEL_PIN = os.getenv("GEMINI_MODEL", "").strip()

# 1회 실행당 신규 처리 상한 (채널 라운드로빈으로 공정 분배). None = 무제한.
# 무료 티어 분당 5회는 429 재시도로 자동 스로틀되고, 일일 쿼터 소진 시 조기 종료되므로
# 무제한이어도 실제 처리량은 그날 가용 쿼터가 자연스럽게 결정한다.
MAX_CANDIDATES_PER_RUN = None

# 아카이브 보관 상한 (최신순 이 개수까지 유지, 초과분은 목록·페이지에서 제거). None = 무제한.
MAX_REPORTS = None

# 백필(과거 영상 열거) 시 채널당 최대 열거 개수 (yt-dlp)
CHANNEL_LOOKBACK = 120

# 스케줄 실행의 기본 백필 시작일. 빈 문자열이면 RSS 최신분만 수집한다(권장).
# ※ 값을 넣으면 '매 실행'이 yt-dlp 로 과거 수백 건을 다시 열거해 백로그를 만들고,
#   한정된 일일 쿼터를 과거 영상이 먹어버려 최신 영상이 계속 밀린다.
#   과거 소급이 필요할 때만 workflow_dispatch 의 since 입력으로 1회성 실행할 것.
BACKFILL_SINCE_DEFAULT = ""

# RSS(최신) 수집 시 이 일수보다 오래된 영상은 후보에서 제외 — 최신 자료 우선 확보용.
MAX_AGE_DAYS = 30

# ---------------------------------------------------------------------------
# 유튜브 쇼츠 제외
# ---------------------------------------------------------------------------
# 쇼츠는 대부분 본편 영상에서 잘라 낸 조각이라, 같은 내용의 리포트가 중복 생성된다.
# 유튜브 쇼츠의 최대 길이는 3분이므로 이 값 이하는 후보에서 제외한다.
# (3분 이하 클립은 그 자체로도 리포트를 만들 만한 분량이 못 된다)
SHORTS_MAX_SECONDS = 180

# 제목·설명에 이 표현이 있으면 길이를 몰라도 쇼츠로 본다 (RSS 는 길이를 주지 않는다)
SHORTS_MARKERS = ["#shorts", "#short", "#쇼츠", "＃shorts"]
