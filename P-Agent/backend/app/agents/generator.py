"""
Generator Agent — 최종 보고서를 생성한다.

생성 경로
---------
1. **Word/PPT** (`report` MCP 서버) — STEP 8 에서 실제 구현
2. **Markdown 대체 저장** (`filesystem` MCP 서버) — 현재 동작함

report 서버가 아직 스텁이므로, 지금은 Markdown 으로 저장해
파이프라인이 끝까지 **실제 산출물**을 만들도록 한다.
STEP 8 에서 report 서버가 구현되면 자동으로 Word/PPT 경로를 타게 된다.

모든 산출물은 `./output` 폴더(프로젝트 내부)에 저장한다. (포터블 원칙)
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.agents.runtime import AgentRuntime
from app.agents.state import AgentState
from app.llm.base import ChatMessage, LLMError

STEP_NAME = "generator"

#: 출력 폴더 (프로젝트 루트 기준 상대경로)
OUTPUT_DIR = "./output"

SYSTEM_PROMPT = """당신은 정부 부처 대응 보고서를 작성하는 담당자입니다.
주어진 근거 자료를 바탕으로 보고서 본문을 작성하세요.

규칙:
- 근거에 없는 내용을 지어내지 마세요.
- 근거를 인용한 문장 끝에는 [출처: 파일명] 형태로 표기하세요.
- '개요 / 주요 내용 / 시사점' 순서의 소제목을 사용하세요.
- 한국어로 작성하세요."""


def safe_filename(title: str) -> str:
    """제목을 파일명으로 쓸 수 있게 정리한다. (경로 구분자/특수문자 제거)"""
    cleaned = re.sub(r"[^\w가-힣 _-]", "", title).strip()
    cleaned = re.sub(r"\s+", "_", cleaned)
    return (cleaned or "보고서")[:50]


def build_markdown(
    title: str, body: str, state: AgentState
) -> str:
    """Markdown 보고서 본문을 조립한다. (각주 포함)"""
    evidences = state.get("evidences", [])
    confidence = state.get("confidence", 0)
    notes = state.get("notes", [])

    lines = [
        f"# {title}",
        "",
        f"- 작성일시: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M')}",
        f"- 신뢰도: {confidence}점 / 100점",
        f"- 근거 자료: {len(evidences)}건",
        "",
        "---",
        "",
        body.strip(),
        "",
    ]

    if evidences:
        lines.extend(["", "## 출처", ""])
        for index, evidence in enumerate(evidences, start=1):
            lines.append(f"{index}. {evidence['source']} ({evidence['origin']})")

    if notes:
        lines.extend(["", "## 참고 사항", ""])
        lines.extend(f"- {note}" for note in notes)

    lines.extend(
        [
            "",
            "---",
            "",
            (
                "> 본 보고서는 P-Agent 가 자동 생성했습니다. "
                "최종 검토 책임은 작성자에게 있습니다."
            ),
        ]
    )
    return "\n".join(lines)


async def _write_body(state: AgentState, runtime: AgentRuntime) -> tuple[str, list[str]]:
    """LLM 으로 보고서 본문을 작성한다. 실패 시 근거를 정리해 대체한다."""
    notes: list[str] = []
    evidences = state.get("evidences", [])

    evidence_text = "\n\n".join(
        f"[출처: {item['source']}]\n{item['content'][:1500]}" for item in evidences[:5]
    ) or "(수집된 근거 자료 없음)"

    prompt = f"요청 내용:\n{state['user_request']}\n\n근거 자료:\n{evidence_text}"

    try:
        response = await runtime.llm.chat(
            [ChatMessage(role="user", content=prompt)],
            system=SYSTEM_PROMPT,
            max_tokens=8000,
        )
        if response.content.strip():
            return response.content, notes
        notes.append("LLM 이 빈 응답을 반환해 근거 요약으로 대체했습니다.")
    except LLMError as exc:
        notes.append(f"본문 작성에 LLM 을 사용하지 못했습니다: {exc.message}")

    # LLM 을 못 쓰는 경우: 수집한 근거를 그대로 정리해 최소한의 결과물을 만든다.
    fallback = ["## 개요", "", state["user_request"], "", "## 수집 자료", ""]
    if evidences:
        for item in evidences:
            fallback.append(f"### {item['source']}")
            fallback.append("")
            fallback.append(item["content"][:1500])
            fallback.append("")
    else:
        fallback.append("수집된 근거 자료가 없습니다.")
    return "\n".join(fallback), notes


async def run(state: AgentState, runtime: AgentRuntime) -> dict[str, Any]:
    """보고서를 생성해 저장한다."""
    run_id = state["run_id"]
    runtime.ensure_alive(run_id)
    await runtime.emit(run_id, "step_started", step=STEP_NAME)

    notes: list[str] = []
    tool_log: list[dict[str, Any]] = []

    title = state["user_request"].strip().splitlines()[0][:60] or "자동 생성 보고서"
    body, body_notes = await _write_body(state, runtime)
    notes.extend(body_notes)

    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    stem = f"{timestamp}_{safe_filename(title)}"

    # --- 1) Word 보고서 시도 (STEP 8 에서 동작) ---
    sections = [{"heading": "본문", "body": body}]
    citations = [
        {"label": item["source"], "source": item["source"]}
        for item in state.get("evidences", [])
    ]
    word_result = await runtime.call_tool(
        STEP_NAME,
        "report__create_word_report",
        {
            "title": title,
            "sections": sections,
            "citations": citations,
            "filename": f"{stem}.docx",
        },
        run_id=run_id,
    )
    tool_log.append(word_result["log"])

    if word_result["ok"]:
        report_path = (word_result["structured"] or {}).get(
            "path", word_result["text"]
        )
        summary = f"보고서를 생성했습니다: {report_path}"
        await runtime.emit(
            run_id, "step_finished", step=STEP_NAME, report_path=report_path
        )
        return {
            "report_path": report_path,
            "summary": summary,
            "notes": notes,
            "tool_log": tool_log,
        }

    # --- 2) Markdown 대체 저장 (현재 경로) ---
    notes.append(
        f"Word 보고서 생성을 사용할 수 없어 Markdown 으로 저장했습니다. "
        f"({word_result['text']})"
    )
    markdown = build_markdown(title, body, state)
    md_path = f"{OUTPUT_DIR}/{stem}.md"

    write_result = await runtime.call_tool(
        STEP_NAME,
        "filesystem__write_file",
        {"path": md_path, "content": markdown},
        run_id=run_id,
    )
    tool_log.append(write_result["log"])

    if write_result["ok"]:
        report_path = (write_result["structured"] or {}).get("path", md_path)
        summary = f"보고서를 생성했습니다: {report_path}"
    else:
        report_path = ""
        summary = "보고서를 저장하지 못했습니다."
        notes.append(f"보고서 저장 실패: {write_result['text']}")

    await runtime.emit(
        run_id, "step_finished", step=STEP_NAME, report_path=report_path
    )
    return {
        "report_path": report_path,
        "summary": summary,
        "notes": notes,
        "tool_log": tool_log,
    }
