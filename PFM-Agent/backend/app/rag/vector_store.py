"""
사내 문서 검색 저장소.

두 가지 백엔드를 지원하며, 사용 가능한 쪽을 자동으로 고른다.

1. **ChromaDB + BGE-M3** (권장)
   - 의미 기반 검색. 표현이 달라도 관련 문서를 찾는다.
   - 임베디드 모드로 동작하며 데이터는 `./data/chroma` 에 저장된다.
   - 로컬 모델(`./models/bge-m3`)이 있어야 한다. (STEP 10 에서 준비)

2. **키워드 검색** (대체 수단)
   - ChromaDB/모델이 없어도 **항상 동작**한다.
   - 단어 빈도 기반의 간단한 점수를 사용한다.
   - 폐쇄망 PC 에 모델을 아직 못 넣었을 때도 RAG 기능이 완전히 죽지 않게 한다.

⚠️ 설계 의도
------------
"모델이 없으면 검색 불가"로 만들면 폐쇄망 초기 도입 시 아무것도 못 한다.
그래서 키워드 검색이라도 되도록 해두고, 어떤 방식으로 검색했는지 결과에 표시한다.
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("pfm-agent.rag")

#: 색인할 수 있는 텍스트 파일 확장자
TEXT_SUFFIXES: tuple[str, ...] = (".md", ".txt", ".json", ".csv", ".yaml", ".yml")

#: 문서를 쪼갤 크기 (글자 수)
CHUNK_SIZE: int = 1000

#: 청크 간 겹치는 글자 수 (문맥 유지)
CHUNK_OVERLAP: int = 150

#: 색인할 최대 파일 크기
MAX_FILE_BYTES: int = 5_000_000

#: 한국어 조사/불용어 (키워드 검색 정확도 향상)
_STOPWORDS: frozenset[str] = frozenset(
    {
        "그리고", "그러나", "또는", "하지만", "때문에", "위해", "대한", "관련",
        "있다", "없다", "한다", "된다", "이다", "에서", "으로", "부터", "까지",
        "the", "and", "for", "with", "that", "this", "from",
    }
)


@dataclass
class SearchResult:
    """검색 결과 한 건."""

    source: str
    """출처 (프로젝트 기준 상대경로)"""

    content: str
    score: float
    """관련도 점수 (0~1, 높을수록 관련성 높음)"""

    method: str = "keyword"
    """검색 방식 ("vector" | "keyword")"""

    def to_dict(self) -> dict[str, Any]:
        """MCP 응답용 dict."""
        return {
            "source": self.source,
            "content": self.content,
            "score": round(self.score, 4),
            "method": self.method,
        }


@dataclass
class DocumentChunk:
    """색인된 문서 조각."""

    source: str
    content: str
    chunk_index: int = 0
    indexed_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        """저장용 dict."""
        return {
            "source": self.source,
            "content": self.content,
            "chunk_index": self.chunk_index,
            "indexed_at": self.indexed_at,
        }


# ============================================================
# 순수 로직 (환경 무관 — 단독 테스트 가능)
# ============================================================


def split_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """
    긴 텍스트를 검색하기 좋은 크기로 나눈다.

    문단 경계를 최대한 지키되, 너무 길면 강제로 자른다.
    앞 조각의 끝부분을 다음 조각에 겹쳐 문맥이 끊기지 않게 한다.
    """
    cleaned = text.strip()
    if not cleaned:
        return []
    if len(cleaned) <= size:
        return [cleaned]

    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        end = start + size
        if end >= len(cleaned):
            chunks.append(cleaned[start:].strip())
            break

        # 문단/문장 경계에서 자르도록 시도한다.
        boundary = max(
            cleaned.rfind("\n\n", start, end),
            cleaned.rfind(". ", start, end),
            cleaned.rfind(".\n", start, end),
        )
        if boundary <= start:
            boundary = end

        chunks.append(cleaned[start:boundary].strip())
        start = max(boundary - overlap, start + 1)

    return [chunk for chunk in chunks if chunk]


#: 한국어 토큰을 쪼갤 문자 n-gram 크기
_NGRAM_SIZE: int = 2

#: n-gram 을 만들 최소 길이 (이보다 짧으면 단어 자체만 사용)
_NGRAM_MIN_LENGTH: int = 3

_HANGUL_PATTERN = re.compile(r"[가-힣]")


def _char_ngrams(token: str, size: int = _NGRAM_SIZE) -> list[str]:
    """단어를 문자 n-gram 으로 쪼갠다. ('배터리' → ['배터', '터리'])"""
    if len(token) < size:
        return []
    return [token[index : index + size] for index in range(len(token) - size + 1)]


def tokenize(text: str) -> list[str]:
    """
    검색용 토큰을 추출한다.

    한글/영문/숫자를 남기고, 불용어와 1글자 토큰은 제외한다.

    ⚠️ 한국어 처리
    --------------
    한국어는 조사가 단어에 붙는 교착어라서 단어 단위로만 비교하면
    '소듐이온배터리' 와 '소듐이온배터리는' 이 서로 다른 토큰이 되어
    검색이 거의 동작하지 않는다.

    형태소 분석기는 폐쇄망 설치 부담이 크므로,
    한글 단어는 **문자 2-gram 을 함께 생성**해 조사가 붙어도 매칭되게 한다.
      '소듐이온배터리는' → 소듐, 듐이, 이온, 온배, 배터, 터리, 리는
      '소듐이온배터리'   → 소듐, 듐이, 이온, 온배, 배터, 터리   (6/7 일치)
    """
    lowered = text.lower()
    raw = re.findall(r"[가-힣a-z0-9]+", lowered)

    tokens: list[str] = []
    for token in raw:
        if len(token) <= 1 or token in _STOPWORDS:
            continue
        tokens.append(token)

        # 한글이 포함된 긴 단어는 n-gram 도 함께 넣는다.
        if len(token) >= _NGRAM_MIN_LENGTH and _HANGUL_PATTERN.search(token):
            tokens.extend(_char_ngrams(token))

    return tokens


def keyword_score(query_tokens: list[str], doc_tokens: list[str]) -> float:
    """
    질문과 문서의 관련도를 0~1 로 계산한다. (TF 기반 코사인 유사도 근사)

    의미 검색만큼 정확하진 않지만, 모델 없이도 동작한다.
    """
    if not query_tokens or not doc_tokens:
        return 0.0

    query_counts = Counter(query_tokens)
    doc_counts = Counter(doc_tokens)

    shared = set(query_counts) & set(doc_counts)
    if not shared:
        return 0.0

    dot = sum(query_counts[token] * doc_counts[token] for token in shared)
    query_norm = math.sqrt(sum(count**2 for count in query_counts.values()))
    doc_norm = math.sqrt(sum(count**2 for count in doc_counts.values()))

    if query_norm == 0 or doc_norm == 0:
        return 0.0
    return dot / (query_norm * doc_norm)


# ============================================================
# 저장소
# ============================================================


class VectorStore:
    """
    사내 문서 검색 저장소.

    Example:
        store = VectorStore(data_dir=Path("./data"))
        store.add_document(Path("./data/policy.md"))
        results = store.search("소듐이온배터리 정책", top_k=5)
    """

    def __init__(
        self,
        *,
        data_dir: Path,
        model_path: Path | None = None,
        chroma_dir: Path | None = None,
    ) -> None:
        """
        Args:
            data_dir: 색인 데이터를 저장할 폴더 (프로젝트 내부)
            model_path: BGE-M3 모델 경로 (없으면 키워드 검색으로 동작)
            chroma_dir: ChromaDB 저장 경로
        """
        self.data_dir = data_dir
        self.model_path = model_path
        self.chroma_dir = chroma_dir or (data_dir / "chroma")
        self.index_path = data_dir / "rag_index.json"

        self._chunks: list[DocumentChunk] = []
        self._tokens: list[list[str]] = []
        self._collection: Any = None
        self._vector_ready = False

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._load_index()
        self._try_init_vector()

    # ------------------------------------------------------------
    # 상태
    # ------------------------------------------------------------
    @property
    def method(self) -> str:
        """현재 사용 중인 검색 방식."""
        return "vector" if self._vector_ready else "keyword"

    @property
    def document_count(self) -> int:
        """색인된 조각 수."""
        return len(self._chunks)

    def status(self) -> dict[str, Any]:
        """상태 요약. (헬스체크/UI 표시용)"""
        return {
            "method": self.method,
            "chunks": self.document_count,
            "sources": len({chunk.source for chunk in self._chunks}),
            "model_available": self._vector_ready,
        }

    # ------------------------------------------------------------
    # 초기화
    # ------------------------------------------------------------
    def _try_init_vector(self) -> None:
        """
        ChromaDB + 로컬 임베딩 모델을 초기화한다.

        실패하면 조용히 키워드 검색으로 동작한다. (폐쇄망 대비)
        """
        if self.model_path is None or not self.model_path.is_dir():
            logger.info("임베딩 모델이 없어 키워드 검색으로 동작합니다: %s", self.model_path)
            return

        # 모델 폴더가 사실상 비어 있으면 사용하지 않는다.
        has_model_files = any(
            path.suffix in {".bin", ".safetensors", ".onnx"}
            for path in self.model_path.rglob("*")
            if path.is_file()
        )
        if not has_model_files:
            logger.info("임베딩 모델 파일이 없어 키워드 검색으로 동작합니다.")
            return

        try:
            import chromadb
            from chromadb.utils import embedding_functions

            embedder = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=str(self.model_path)
            )
            client = chromadb.PersistentClient(path=str(self.chroma_dir))
            self._collection = client.get_or_create_collection(
                name="internal_docs", embedding_function=embedder
            )
            self._vector_ready = True
            logger.info("의미 기반 검색(ChromaDB + BGE-M3) 준비 완료")
        except ImportError:
            logger.info("ChromaDB 가 설치되어 있지 않아 키워드 검색으로 동작합니다.")
        except Exception as exc:  # noqa: BLE001 - 어떤 실패든 키워드 검색으로 대체
            logger.warning("의미 검색 초기화 실패, 키워드 검색으로 동작합니다: %s", exc)

    # ------------------------------------------------------------
    # 색인 저장/로드
    # ------------------------------------------------------------
    def _load_index(self) -> None:
        """저장된 색인을 읽는다."""
        if not self.index_path.is_file():
            return
        try:
            raw = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("색인 파일을 읽지 못했습니다: %s", exc)
            return

        self._chunks = [
            DocumentChunk(
                source=item["source"],
                content=item["content"],
                chunk_index=item.get("chunk_index", 0),
                indexed_at=item.get("indexed_at", ""),
            )
            for item in raw.get("chunks", [])
        ]
        self._tokens = [tokenize(chunk.content) for chunk in self._chunks]

    def _save_index(self) -> None:
        """색인을 파일에 저장한다."""
        payload = {
            "updated_at": datetime.now(UTC).isoformat(),
            "chunks": [chunk.to_dict() for chunk in self._chunks],
        }
        try:
            self.index_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:  # pragma: no cover
            logger.warning("색인을 저장하지 못했습니다: %s", exc)

    # ------------------------------------------------------------
    # 색인 추가
    # ------------------------------------------------------------
    def add_text(self, source: str, text: str) -> int:
        """
        텍스트를 색인에 추가한다.

        Returns:
            추가된 조각 수
        """
        # 같은 출처의 기존 조각은 교체한다. (중복 방지)
        self.remove_source(source)

        pieces = split_text(text)
        for index, piece in enumerate(pieces):
            self._chunks.append(
                DocumentChunk(source=source, content=piece, chunk_index=index)
            )
            self._tokens.append(tokenize(piece))

        if self._vector_ready and pieces and self._collection is not None:
            try:
                self._collection.upsert(
                    ids=[f"{source}#{index}" for index in range(len(pieces))],
                    documents=pieces,
                    metadatas=[{"source": source} for _ in pieces],
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("벡터 색인 추가 실패, 키워드 검색만 사용합니다: %s", exc)

        self._save_index()
        return len(pieces)

    def add_document(self, path: Path, *, relative_to: Path | None = None) -> int:
        """
        파일을 읽어 색인에 추가한다.

        Returns:
            추가된 조각 수

        Raises:
            ValueError: 읽을 수 없는 파일인 경우 (한글 메시지)
        """
        if not path.is_file():
            raise ValueError(f"파일을 찾을 수 없습니다: {path}")
        if path.suffix.lower() not in TEXT_SUFFIXES:
            raise ValueError(
                f"'{path.suffix}' 형식은 색인할 수 없습니다. "
                f"({', '.join(TEXT_SUFFIXES)} 만 지원)"
            )
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError(
                f"파일이 너무 큽니다 ({path.stat().st_size:,} 바이트). "
                f"{MAX_FILE_BYTES:,} 바이트 이하만 색인할 수 있습니다."
            )

        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(
                f"'{path.name}' 은(는) UTF-8 텍스트 파일이 아닙니다."
            ) from exc

        source = (
            path.relative_to(relative_to).as_posix() if relative_to else path.as_posix()
        )
        return self.add_text(source, text)

    def remove_source(self, source: str) -> int:
        """
        특정 출처의 조각을 모두 제거한다.

        Returns:
            제거된 조각 수
        """
        keep_chunks: list[DocumentChunk] = []
        keep_tokens: list[list[str]] = []
        removed = 0

        for chunk, tokens in zip(self._chunks, self._tokens, strict=False):
            if chunk.source == source:
                removed += 1
                continue
            keep_chunks.append(chunk)
            keep_tokens.append(tokens)

        self._chunks = keep_chunks
        self._tokens = keep_tokens
        return removed

    def clear(self) -> None:
        """색인을 모두 비운다."""
        self._chunks.clear()
        self._tokens.clear()
        self.index_path.unlink(missing_ok=True)

    # ------------------------------------------------------------
    # 검색
    # ------------------------------------------------------------
    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        """
        질문과 관련된 문서 조각을 찾는다.

        의미 검색이 가능하면 그것을 쓰고, 아니면 키워드 검색으로 대체한다.
        """
        if not query.strip():
            return []

        if self._vector_ready and self._collection is not None:
            results = self._search_vector(query, top_k)
            if results:
                return results
            # 벡터 검색이 실패하거나 결과가 없으면 키워드로 재시도한다.

        return self._search_keyword(query, top_k)

    def _search_vector(self, query: str, top_k: int) -> list[SearchResult]:
        """의미 기반 검색 (ChromaDB)."""
        try:
            response = self._collection.query(query_texts=[query], n_results=top_k)
        except Exception as exc:  # noqa: BLE001
            logger.warning("의미 검색 실패, 키워드 검색으로 대체합니다: %s", exc)
            return []

        documents = (response.get("documents") or [[]])[0]
        metadatas = (response.get("metadatas") or [[]])[0]
        distances = (response.get("distances") or [[]])[0]

        results: list[SearchResult] = []
        for document, metadata, distance in zip(
            documents, metadatas, distances, strict=False
        ):
            # 거리(작을수록 유사) → 점수(클수록 유사)
            score = 1.0 / (1.0 + float(distance))
            results.append(
                SearchResult(
                    source=str((metadata or {}).get("source", "사내 문서")),
                    content=document,
                    score=score,
                    method="vector",
                )
            )
        return results

    def _search_keyword(self, query: str, top_k: int) -> list[SearchResult]:
        """키워드 기반 검색 (모델 없이 동작)."""
        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        scored: list[tuple[float, DocumentChunk]] = []
        for chunk, tokens in zip(self._chunks, self._tokens, strict=False):
            score = keyword_score(query_tokens, tokens)
            if score > 0:
                scored.append((score, chunk))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [
            SearchResult(
                source=chunk.source, content=chunk.content, score=score, method="keyword"
            )
            for score, chunk in scored[:top_k]
        ]
