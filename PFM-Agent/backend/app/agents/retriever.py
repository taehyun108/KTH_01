"""
Retriever Agent — 근거 자료를 수집한다.

수집 경로 (우선순위)
--------------------
1. **사내 RAG** (`rag` MCP 서버) — STEP 7 에서 실제 구현
2. **로컬 자료 폴더** (`filesystem` MCP 서버, `./data`) — 현재 동작함
3. 웹 검색 — 선택 기능이며 폐쇄망에서는 사용하지 않는다.

폐쇄망 원칙: 사내 RAG 만으로도 동작해야 하며,
외부 검색이 실패해도 수집 결과가 비지 않도록 로컬 자료를 함께 확인한다.

재검색 (피드백 루프)
--------------------
Verifier 가 신뢰도 미달로 판단하면 이 노드가 **다시 호출된다.**
그때는 `search_queries` 에 담긴 대체 검색어를 사용하고, 이전 회차의 근거를
버리지 않고 **누적**한다. 진입 시 `retry_reason` 을 비워 무한 루프를 막는다.
"""

from __future__ import annotations

from typing import Any

from app.agents.feedback import merge_evidences
from app.agents.runtime import AgentRuntime
from app.agents.state import AgentState, Evidence

STEP_NAME = "retriever"

#: 로컬에서 근거 자료를 찾을 폴더
LOCAL_DATA_DIR = "./data"

#: 로컬 자료로 읽어들일 최대 파일 수
MAX_LOCAL_FILES = 5

#: 근거로 저장할 본문 최대 길이
MAX_EVIDENCE_CHARS = 4000

#: 텍스트로 읽을 수 있는 확장자
TEXT_SUFFIXES = (".md", ".txt", ".json", ".csv", ".yaml", ".yml")


async def _collect_from_rag(
    state: AgentState, runtime: AgentRuntime, query: str
) -> tuple[list[Evidence], list[str], list[dict[str, Any]]]:
    """
    사내 RAG 에서 근거를 수집한다.

    Args:
        query: 이번에 사용할 검색어 (재검색 시에는 대체 검색어가 들어온다)
    """
    run_id = state["run_id"]
    evidences: list[Evidence] = []
    notes: list[str] = []
    tool_log: list[dict[str, Any]] = []

    result = await runtime.call_tool(
        STEP_NAME,
        "rag__search_internal_docs",
        {"query": query, "top_k": runtime.settings.rag_top_k},
        run_id=run_id,
    )
    tool_log.append(result["log"])

    if result["ok"]:
        structured = result["structured"] or {}
        for item in structured.get("results", []):
            evidences.append(
                Evidence(
                    source=str(item.get("source", "사내 문서")),
                    content=str(item.get("content", ""))[:MAX_EVIDENCE_CHARS],
                    origin="rag",
                )
            )
        if not evidences and result["text"]:
            evidences.append(
                Evidence(
                    source="사내 RAG",
                    content=result["text"][:MAX_EVIDENCE_CHARS],
                    origin="rag",
                )
            )
    else:
        notes.append(f"사내 문서 검색을 사용할 수 없습니다: {result['text']}")

    return evidences, notes, tool_log


async def _collect_from_local(
    state: AgentState, runtime: AgentRuntime
) -> tuple[list[Evidence], list[str], list[dict[str, Any]]]:
    """로컬 `./data` 폴더의 텍스트 자료를 근거로 수집한다."""
    run_id = state["run_id"]
    evidences: list[Evidence] = []
    notes: list[str] = []
    tool_log: list[dict[str, Any]] = []

    listing = await runtime.call_tool(
        STEP_NAME, "filesystem__list_dir", {"path": LOCAL_DATA_DIR}, run_id=run_id
    )
    tool_log.append(listing["log"])

    if not listing["ok"]:
        notes.append("로컬 자료 폴더(./data)를 읽지 못했습니다.")
        return evidences, notes, tool_log

    entries = (listing["structured"] or {}).get("entries", [])
    text_files = [
        entry
        for entry in entries
        if entry.get("type") == "file"
        and str(entry.get("name", "")).lower().endswith(TEXT_SUFFIXES)
    ][:MAX_LOCAL_FILES]

    if not text_files:
        notes.append("로컬 자료 폴더(./data)에 참고할 문서가 없습니다.")
        return evidences, notes, tool_log

    for entry in text_files:
        read = await runtime.call_tool(
            STEP_NAME,
            "filesystem__read_file",
            {"path": entry["path"]},
            run_id=run_id,
        )
        tool_log.append(read["log"])
        if not read["ok"]:
            continue
        content = (read["structured"] or {}).get("content", read["text"])
        evidences.append(
            Evidence(
                source=entry["path"],
                content=str(content)[:MAX_EVIDENCE_CHARS],
                origin="file",
            )
        )

    return evidences, notes, tool_log


def resolve_queries(state: AgentState) -> list[str]:
    """
    이번 회차에 사용할 검색어를 결정한다.

    - 첫 회차: 사용자 요청문 그대로
    - 재검색:  Verifier 가 제안한 `search_queries`
    """
    queries = [item for item in state.get("search_queries", []) if item.strip()]
    return queries or [state["user_request"]]


async def run(state: AgentState, runtime: AgentRuntime) -> dict[str, Any]:
    """근거 자료를 수집한다. (재검색 시에는 이전 근거에 누적한다)"""
    run_id = state["run_id"]
    runtime.ensure_alive(run_id)

    iteration = state.get("iteration") or 1
    queries = resolve_queries(state)
    await runtime.emit(
        run_id,
        "step_started",
        step=STEP_NAME,
        iteration=iteration,
        queries=queries,
    )

    fresh: list[Evidence] = []
    notes: list[str] = []
    tool_log: list[dict[str, Any]] = []

    # 1) 사내 RAG — 검색어별로 조회한다. (재검색 시 여러 개가 들어올 수 있음)
    for query in queries:
        runtime.ensure_alive(run_id)
        rag_evidences, rag_notes, rag_log = await _collect_from_rag(
            state, runtime, query
        )
        fresh.extend(rag_evidences)
        notes.extend(rag_notes)
        tool_log.extend(rag_log)

    # 이전 회차 근거와 합친다. (재검색은 누적 — 찾은 것을 버리지 않는다)
    evidences = merge_evidences(state.get("evidences", []), fresh)

    # 2) 로컬 자료 (근거가 하나도 없을 때만 보완)
    #    이미 로컬 자료를 담아 왔다면 evidences 가 비지 않으므로 다시 읽지 않는다.
    if not evidences:
        local_evidences, local_notes, local_log = await _collect_from_local(
            state, runtime
        )
        evidences = merge_evidences(evidences, local_evidences)
        notes.extend(local_notes)
        tool_log.extend(local_log)

    if not evidences:
        notes.append(
            "참고할 근거 자료를 찾지 못했습니다. 보고서는 요청 내용만으로 작성됩니다."
        )
    elif iteration > 1:
        notes.append(
            f"재검색으로 근거가 {len(evidences)}건이 되었습니다. "
            f"(새로 찾은 자료 {len(evidences) - len(state.get('evidences', []))}건)"
        )

    await runtime.emit(
        run_id,
        "step_finished",
        step=STEP_NAME,
        evidence_count=len(evidences),
        iteration=iteration,
    )
    return {
        "evidences": evidences,
        "notes": notes,
        "tool_log": tool_log,
        # 시도한 검색어를 기록해 다음 회차에 같은 검색어를 쓰지 않게 한다.
        "tried_queries": queries,
        # ★ 무한 루프 방지: 재검색 요청을 여기서 반드시 소비(초기화)한다.
        "retry_reason": "",
        # 다음 회차 검색어는 Verifier 가 다시 채운다.
        "search_queries": [],
    }
