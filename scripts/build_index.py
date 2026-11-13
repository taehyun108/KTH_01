"""
3단계: /site/data/reports.json 인덱스 갱신.

읽기·병합·삭제는 모두 report_archive 가 맡는다. 이 모듈은 기존 호출처
(run_pipeline·regenerate·summarize_url …)가 쓰던 이름을 그대로 내주는 얇은 입구다.
"""
from __future__ import annotations

from report_archive import load as load_existing, merge  # noqa: F401


if __name__ == "__main__":
    merge([])  # 정렬/타임스탬프만 갱신
