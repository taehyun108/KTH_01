"""
파이프라인 공용 설정 — 채널 목록, 키워드, 경로.

채널 ID(channel_id)는 유튜브 채널 페이지 → '정보' 탭 또는 페이지 소스에서 확인 후
아래 CHANNELS 의 channel_id 를 채워 넣으세요. (현재는 뼈대용 placeholder)
"""

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
    {"name": "삼프로TV",            "channel_id": "UChlv4GSd7OQl3js-jkLOnFA"},
    {"name": "슈카월드",            "channel_id": "UCsJ6RuBiTVWRX156FVbeaGg"},
    {"name": "언더스탠딩",          "channel_id": "UCIUni4ScRp4mqPXsxy62L5w"},
    {"name": "소수몽키",            "channel_id": "UCC3yfxS5qC6PCwDzetUuEWg"},
    {"name": "전인구경제연구소",     "channel_id": "UCznImSIaxZR7fdLCICLdgaQ"},
    {"name": "슈퍼개미 이세무사TV",  "channel_id": "UCowHl0BGalL433P6bCBgeKA"},
    # 필요 시 채널 추가: {"name": "조선비즈", "channel_id": "UC..."},
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

KW_MACRO = [  # (C) 거시/산업 간접
    "금리", "연준", "FOMC", "관세", "무역분쟁", "수출규제", "전력망", "정전",
    "전기료", "화재", "폭발", "안전사고", "안전기준", "인증", "ESG",
    "공급망", "지정학", "중국 산업정책",
]

ALL_KEYWORDS = KW_DIRECT + KW_APPLICATION + KW_MACRO

# 카테고리 정의 (LLM 분류가 이 중 하나를 반환)
CATEGORIES = ["global-policy", "global-market", "korea-policy", "korea-market"]

# Gemini 모델 (시크릿 KTH_01_GEMINI_API_KEY → 환경변수 GEMINI_API_KEY)
# 실제 사용 모델은 런타임에 generateContent 지원 목록에서 자동 선택되며,
# 아래 값은 목록 조회 실패 시의 최종 폴백입니다.
GEMINI_MODEL = "gemini-2.5-flash"

# 1회 실행당 신규 처리 상한 (채널 라운드로빈으로 공정 분배)
# 무료 티어 분당 5회는 429 재시도로 자동 스로틀됨. 실제 후보는 RSS 최근분(채널당 ~15)으로
# 제한되므로, 이 값은 사실상 "가용한 신규 영상을 최대 N건까지 처리".
MAX_CANDIDATES_PER_RUN = 300

# 아카이브 보관 상한 (최신순 이 개수까지 유지, 초과분은 목록·페이지에서 제거)
MAX_REPORTS = 300

# 백필(과거 영상 열거) 시 채널당 최대 열거 개수 (yt-dlp)
CHANNEL_LOOKBACK = 400
