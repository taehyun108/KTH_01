"""
Retriever Agent — 근거 자료를 수집한다.

수집 경로 (우선순위)
--------------------
1. **사내 RAG** (`rag` MCP 서버) — STEP 7 에서 실제 구현
2. **로컬 자료 폴더** (`filesystem` MCP 서버, `./data`) — 현재 동작함
3. 웹 검색 — 선택 기능이며 폐쇄망에서는 사용하지 않는다.

폐쇄망 원칙: 사내 RAG 만으로도 동작해야 하며,
외부 검색이 실패해도 수집 결과가 비지 않도록 로컬 자료를 함께 확인한다.
"""

from __future__ import annotations

from typing import Any

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
    state: AgentState, runtime: AgentRuntime
) -> tuple[list[Evidence], list[str], list[dict[str, Any]]]:
    """사내 RAG 에서 근거를 수집한다."""
    run_id = state["run_id"]
    evidences: list[Evidence] = []
    notes: list[str] = []
    tool_log: list[dict[str, Any]] = []

    result = await runtime.call_tool(
        STEP_NAME,
        "rag__search_internal_docs",
        {"query": state["user_request"], "top_k": runtime.settings.rag_top_k},
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


async def run(state: AgentState, runtime: AgentRuntime) -> dict[str, Any]:
    """근거 자료를 수집한다."""
    run_id = state["run_id"]
    runtime.ensure_alive(run_id)
    await runtime.emit(run_id, "step_started", step=STEP_NAME)

    evidences: list[Evidence] = []
    notes: list[str] = []
    tool_log: list[dict[str, Any]] = []

    # 1) 사내 RAG
    rag_evidences, rag_notes, rag_log = await _collect_from_rag(state, runtime)
    evidences.extend(rag_evidences)
    notes.extend(rag_notes)
    tool_log.extend(rag_log)

    # 2) 로컬 자료 (RAG 가 비어 있을 때 보완)
    if not evidences:
        local_evidences, local_notes, local_log = await _collect_from_local(
            state, runtime
        )
        evidences.extend(local_evidences)
        notes.extend(local_notes)
        tool_log.extend(local_log)

    if not evidences:
        notes.append(
            "참고할 근거 자료를 찾지 못했습니다. 보고서는 요청 내용만으로 작성됩니다."
        )

    await runtime.emit(
        run_id, "step_finished", step=STEP_NAME, evidence_count=len(evidences)
    )
    return {"evidences": evidences, "notes": notes, "tool_log": tool_log}
