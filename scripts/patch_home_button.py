"""
이미 생성된 리포트 HTML 에 홈 버튼을 주입하는 일회성 패치 (LLM 미사용 = 쿼터 0).

render_html 은 앞으로 생성되는 리포트에만 적용되므로, 과거 리포트도 동일하게
우측 상단 홈 버튼을 갖도록 <body> 직후에 앵커를 삽입하고 스타일 캐시 버전을 올린다.
이미 버튼이 있으면 건너뛰므로 여러 번 실행해도 안전하다.
"""
from __future__ import annotations

import re

from config import NEWS_DIR

CSS_VER = 20
NAV = (
    '\n        <nav class="top-nav">'
    '\n          <a class="home-btn" href="../news/" title="홈으로" aria-label="홈으로 이동">홈</a>'
    '\n          <a class="home-btn" href="../glossary/?v=20" title="이차전지 용어집">용어집</a>'
    '\n        </nav>'
)


def main() -> int:
    patched = skipped = 0
    for f in sorted(NEWS_DIR.glob("*.html")):
        if f.name == "index.html":
            continue
        html = f.read_text(encoding="utf-8")
        orig = html

        # 기존 헤더 링크(단독 홈 버튼 또는 이전 nav)를 걷어내고 메타 줄 안쪽 끝에 다시 배치
        html = re.sub(r'\s*<nav class="top-nav">.*?</nav>', "", html, flags=re.DOTALL)
        html = re.sub(r'\s*<a class="home-btn".*?</a>', "", html, flags=re.DOTALL)
        html = html.replace(
            "<span>🎬 영상</span>\n      </div>",
            "<span>🎬 영상</span>" + NAV + "\n      </div>",
            1,
        )

        # 새 CSS(.home-btn)를 받도록 캐시 버전 갱신
        html = re.sub(r'(assets/style\.css\?v=)\d+', rf'\g<1>{CSS_VER}', html)

        if html != orig:
            f.write_text(html, encoding="utf-8")
            patched += 1
        else:
            skipped += 1

    print(f"홈 버튼 패치 완료 — 수정 {patched}건, 변경 없음 {skipped}건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
