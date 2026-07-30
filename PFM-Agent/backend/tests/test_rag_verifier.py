"""
STEP 7 검증: Retriever & Verifier 테스트.

  - 개인정보 마스킹
  - 문서 분할 / 키워드 검색 (모델 없이 동작해야 함 — 폐쇄망 대비)
  - 화이트리스트 기반 근거 필터
  - 신뢰도 스코어링
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.state import Evidence
from app.agents.verifier import (
    LOW_CONFIDENCE_THRESHOLD,
    filter_by_whitelist,
    is_web_source,
    mask_evidences,
    rule_based_score,
)
from app.rag.vector_store import (
    VectorStore,
    keyword_score,
    split_text,
    tokenize,
)
from app.security.masking import (
    contains_personal_info,
    mask_dict,
    mask_text,
)

# ============================================================
# 1. 개인정보 마스킹
# ============================================================


def test_mask_resident_registration_number() -> None:
    """🔴 주민등록번호 뒤 7자리가 가려져야 한다."""
    result = mask_text("담당자 주민번호는 900101-1234567 입니다.")
    assert "900101-*******" in result.text
    assert "1234567" not in result.text
    assert result.counts["주민등록번호"] == 1


def test_mask_phone_number() -> None:
    """🔴 휴대전화번호 가운데가 가려져야 한다."""
    result = mask_text("연락처: 010-1234-5678")
    assert "010-****-5678" in result.text
    assert "1234" not in result.text.split("-")[1]
    assert result.counts["휴대전화번호"] == 1


def test_mask_phone_without_hyphen() -> None:
    """하이픈 없는 번호도 인식해야 한다."""
    result = mask_text("연락처 01012345678 로 전화주세요")
    assert result.found_any


def test_mask_email() -> None:
    """🔴 이메일 아이디가 가려져야 한다."""
    result = mask_text("문의: hong.gildong@posco.com")
    assert "h***@posco.com" in result.text
    assert "gildong" not in result.text
    assert result.counts["이메일"] == 1


def test_mask_card_number() -> None:
    """🔴 카드번호는 마지막 4자리만 남아야 한다."""
    result = mask_text("결제카드 1234-5678-9012-3456")
    assert "****-****-****-3456" in result.text
    assert "5678" not in result.text


def test_mask_multiple_types_at_once() -> None:
    """여러 종류가 섞여 있어도 모두 처리해야 한다."""
    text = "홍길동(010-1234-5678, hong@posco.com) 주민번호 900101-1234567"
    result = mask_text(text)

    assert result.total == 3
    assert "1234567" not in result.text
    assert "hong@" not in result.text
    assert "주민등록번호" in result.summary()


def test_mask_preserves_normal_text() -> None:
    """개인정보가 아닌 숫자는 건드리지 않아야 한다."""
    text = "소듐이온배터리 생산량은 2024년 기준 1500톤입니다."
    result = mask_text(text)
    assert result.text == text
    assert result.found_any is False
    assert "발견되지 않았습니다" in result.summary()


def test_mask_empty_text() -> None:
    """빈 텍스트도 안전하게 처리해야 한다."""
    assert mask_text("").text == ""
    assert mask_text("").found_any is False


def test_contains_personal_info() -> None:
    """개인정보 포함 여부 판단."""
    assert contains_personal_info("010-1234-5678") is True
    assert contains_personal_info("정책 동향 분석") is False


def test_mask_dict_walks_nested() -> None:
    """중첩된 dict/list 안의 문자열까지 마스킹되어야 한다."""
    data = {
        "title": "보고서",
        "author": {"email": "hong@posco.com"},
        "contacts": ["010-1234-5678", "정상 텍스트"],
    }
    masked, counts = mask_dict(data)

    assert "h***@posco.com" == masked["author"]["email"]
    assert "010-****-5678" == masked["contacts"][0]
    assert masked["contacts"][1] == "정상 텍스트"
    assert counts["이메일"] == 1
    assert counts["휴대전화번호"] == 1


# ============================================================
# 2. 문서 분할 / 토큰화
# ============================================================


def test_split_short_text_stays_single() -> None:
    """짧은 글은 나누지 않아야 한다."""
    assert split_text("짧은 문서입니다.") == ["짧은 문서입니다."]


def test_split_long_text_creates_chunks() -> None:
    """긴 글은 여러 조각으로 나뉘어야 한다."""
    text = "가나다라마바사. " * 500  # 약 4000자
    chunks = split_text(text, size=1000, overlap=100)

    assert len(chunks) > 1
    assert all(len(chunk) <= 1200 for chunk in chunks)  # 경계 보정 여유


def test_split_empty_text() -> None:
    """빈 글은 빈 목록을 반환해야 한다."""
    assert split_text("") == []
    assert split_text("   ") == []


def test_tokenize_removes_stopwords_and_short() -> None:
    """불용어와 1글자 토큰이 제거되어야 한다."""
    tokens = tokenize("소듐이온배터리 그리고 정책 은 A")
    assert "소듐이온배터리" in tokens
    assert "정책" in tokens
    assert "그리고" not in tokens  # 불용어
    assert "a" not in tokens  # 1글자


def test_keyword_score_relevance() -> None:
    """관련 있는 문서가 더 높은 점수를 받아야 한다."""
    query = tokenize("소듐이온배터리 정책")
    relevant = tokenize("소듐이온배터리 정책 동향과 지원 방안")
    unrelated = tokenize("점심 메뉴 추천 목록")

    assert keyword_score(query, relevant) > keyword_score(query, unrelated)
    assert keyword_score(query, unrelated) == 0.0


def test_keyword_score_empty() -> None:
    """빈 입력은 0점이어야 한다."""
    assert keyword_score([], ["문서"]) == 0.0
    assert keyword_score(["질문"], []) == 0.0


def test_tokenize_handles_korean_particles() -> None:
    """
    🔴 한국어 검색 핵심: 조사가 붙어도 매칭되어야 한다.

    한국어는 교착어라 '소듐이온배터리' 와 '소듐이온배터리는' 이
    단어 단위로는 서로 다른 토큰이 된다.
    문자 2-gram 을 함께 생성해 이 문제를 해결한다.
    """
    query = tokenize("소듐이온배터리")
    doc = tokenize("소듐이온배터리는 원가가 낮다")

    # 단어 자체는 다르지만 n-gram 이 겹쳐야 한다.
    assert set(query) & set(doc), "조사가 붙으면 전혀 매칭되지 않습니다"
    assert keyword_score(query, doc) > 0


def test_tokenize_korean_ngrams_generated() -> None:
    """한글 단어에서 문자 2-gram 이 생성되어야 한다."""
    tokens = tokenize("배터리")
    assert "배터리" in tokens
    assert "배터" in tokens
    assert "터리" in tokens


def test_tokenize_english_no_ngrams() -> None:
    """영문 단어는 n-gram 을 만들지 않는다. (불필요한 오탐 방지)"""
    tokens = tokenize("battery policy")
    assert "battery" in tokens
    assert "ba" not in tokens


# ============================================================
# 3. 검색 저장소 (모델 없이 동작해야 함 — 폐쇄망 대비)
# ============================================================


@pytest.fixture
def store(tmp_path: Path) -> VectorStore:
    """모델이 없는 상태의 저장소. (키워드 검색으로 동작)"""
    return VectorStore(data_dir=tmp_path, model_path=tmp_path / "없는모델")


def test_store_works_without_model(store: VectorStore) -> None:
    """
    🔴 폐쇄망 대비: 임베딩 모델이 없어도 검색 저장소가 동작해야 한다.
    (모델이 없다고 기능이 완전히 죽으면 안 된다)
    """
    assert store.method == "keyword"
    assert store.status()["model_available"] is False


def test_store_add_and_search(store: VectorStore) -> None:
    """추가한 문서를 검색할 수 있어야 한다."""
    store.add_text(
        "policy.md",
        "소듐이온배터리는 리튬 대비 원가가 낮아 ESS 분야에서 주목받고 있다. "
        "정부는 2025년부터 관련 지원 정책을 확대할 예정이다.",
    )
    store.add_text("lunch.md", "오늘 점심은 김치찌개와 제육볶음입니다.")

    results = store.search("소듐이온배터리 정책", top_k=5)

    assert len(results) >= 1
    assert results[0].source == "policy.md"
    assert results[0].score > 0
    assert results[0].method == "keyword"


def test_store_search_empty_query(store: VectorStore) -> None:
    """빈 질문은 빈 결과를 반환해야 한다."""
    store.add_text("doc.md", "내용")
    assert store.search("") == []


def test_store_replaces_same_source(store: VectorStore) -> None:
    """같은 출처를 다시 추가하면 교체되어야 한다. (중복 방지)"""
    store.add_text("doc.md", "첫 번째 내용 소듐이온배터리")
    first_count = store.document_count

    store.add_text("doc.md", "두 번째 내용 소듐이온배터리")

    assert store.document_count == first_count  # 늘어나지 않음
    results = store.search("소듐이온배터리")
    assert "두 번째" in results[0].content


def test_store_persists_index(tmp_path: Path) -> None:
    """색인이 파일로 저장되어 재시작 후에도 유지되어야 한다."""
    store = VectorStore(data_dir=tmp_path, model_path=None)
    store.add_text("policy.md", "소듐이온배터리 정책 동향 분석 자료")

    # 새 인스턴스로 다시 읽기 (앱 재시작 상황)
    reopened = VectorStore(data_dir=tmp_path, model_path=None)

    assert reopened.document_count == store.document_count
    assert len(reopened.search("소듐이온배터리")) >= 1


def test_store_add_document_from_file(tmp_path: Path) -> None:
    """파일을 읽어 색인에 추가할 수 있어야 한다."""
    doc = tmp_path / "policy.md"
    doc.write_text("소듐이온배터리 정책 동향", encoding="utf-8")

    store = VectorStore(data_dir=tmp_path, model_path=None)
    added = store.add_document(doc, relative_to=tmp_path)

    assert added >= 1
    assert store.search("소듐이온배터리")[0].source == "policy.md"


def test_store_rejects_unsupported_file(tmp_path: Path) -> None:
    """지원하지 않는 형식은 한글 안내와 함께 거부되어야 한다."""
    binary = tmp_path / "image.png"
    binary.write_bytes(b"\x89PNG")

    store = VectorStore(data_dir=tmp_path, model_path=None)
    with pytest.raises(ValueError) as excinfo:
        store.add_document(binary)
    assert "색인할 수 없습니다" in str(excinfo.value)


def test_store_rejects_missing_file(tmp_path: Path) -> None:
    """없는 파일은 거부되어야 한다."""
    store = VectorStore(data_dir=tmp_path, model_path=None)
    with pytest.raises(ValueError) as excinfo:
        store.add_document(tmp_path / "없는파일.md")
    assert "찾을 수 없습니다" in str(excinfo.value)


# ============================================================
# 4. Verifier — 화이트리스트 필터
# ============================================================


def test_is_web_source() -> None:
    """웹 출처와 파일 출처를 구분해야 한다."""
    assert is_web_source("https://www.motie.go.kr/policy") is True
    assert is_web_source("data/policy.md") is False
    assert is_web_source("사내 문서") is False


def test_filter_keeps_internal_sources() -> None:
    """사내 문서·로컬 파일은 화이트리스트 검사 대상이 아니다."""
    evidences = [
        Evidence(source="data/policy.md", content="내용", origin="file"),
        Evidence(source="사내 RAG", content="내용", origin="rag"),
    ]
    kept, rejected = filter_by_whitelist(evidences)

    assert len(kept) == 2
    assert rejected == []


def test_filter_removes_unlisted_web_source() -> None:
    """🔴 보안: 허용되지 않은 웹 출처는 근거에서 제외되어야 한다."""
    evidences = [
        Evidence(source="https://www.motie.go.kr/x", content="허용", origin="web"),
        Evidence(source="https://evil.example.com/x", content="차단", origin="web"),
    ]
    kept, rejected = filter_by_whitelist(evidences)

    assert len(kept) == 1
    assert kept[0]["source"] == "https://www.motie.go.kr/x"
    assert len(rejected) == 1
    assert "근거 제외" in rejected[0]


# ============================================================
# 5. Verifier — 마스킹 / 점수
# ============================================================


def test_mask_evidences_hides_personal_info() -> None:
    """🔴 근거 본문의 개인정보가 가려져야 한다."""
    evidences = [
        Evidence(
            source="data/contact.md",
            content="담당자 010-1234-5678, hong@posco.com",
            origin="file",
        )
    ]
    masked, count = mask_evidences(evidences)

    assert count == 2
    assert "1234-5678" not in masked[0]["content"]
    assert "hong@" not in masked[0]["content"]
    assert masked[0]["source"] == "data/contact.md"  # 출처는 유지


def test_rule_based_score_no_evidence_is_low() -> None:
    """근거가 없으면 낮은 점수여야 한다."""
    score = rule_based_score(0, False)
    assert score < LOW_CONFIDENCE_THRESHOLD


def test_rule_based_score_increases_with_evidence() -> None:
    """근거가 많을수록 점수가 올라가야 한다."""
    assert rule_based_score(3, False) > rule_based_score(1, False)


def test_rule_based_score_penalizes_local_only() -> None:
    """사내 RAG 없이 로컬 파일만 있으면 소폭 감점되어야 한다."""
    assert rule_based_score(2, True) < rule_based_score(2, False)


def test_rule_based_score_capped() -> None:
    """점수는 0~100 범위를 벗어나지 않아야 한다."""
    for count in (0, 1, 5, 100):
        for local_only in (True, False):
            assert 0 <= rule_based_score(count, local_only) <= 100
