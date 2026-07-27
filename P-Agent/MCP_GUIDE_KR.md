# 🔌 P-Agent MCP 구조 가이드 (개발자용)

이 문서는 **다른 개발자가 P-Agent에 새 도구를 추가**할 수 있도록 MCP 구조를 설명합니다.
이 문서만 보고도 새로운 도구 서버를 만들거나 기존 서버에 도구를 추가할 수 있어야 합니다.

---

## 1. MCP란?

**MCP (Model Context Protocol)** 는 LLM/Agent가 외부 "도구(tool)"를 표준화된 방식으로
호출하기 위한 프로토콜입니다. Anthropic이 공개한 오픈 표준이며, 전송 방식으로
**JSON-RPC 2.0 over stdio**(표준 입출력)를 사용합니다.

```
[LangGraph Agent] ──(도구 호출)──▶ [MCP Client] ──(JSON-RPC/stdio)──▶ [MCP Server] ──▶ 실제 도구 실행
```

- **MCP Server**: 실제 도구(파일 읽기, 스크린샷 등)를 구현한 독립 프로세스
- **MCP Client**: Agent 대신 서버를 실행/호출하고 결과를 받아오는 중개자

### ⚠️ 개발용 MCP vs 런타임 MCP (혼동 금지)

| 구분 | 개발용 MCP | 런타임 MCP (본 문서 대상) |
|---|---|---|
| 위치 | Claude Code 데스크톱 앱 | **P-Agent 앱 내부** |
| 예시 | filesystem, github, playwright | filesystem/screen/automation/rag/report |
| 목적 | 개발 생산성 향상 | Agent의 실제 도구 실행 |
| 배포 | ❌ USB에 포함하지 않음 | ✅ P-Agent 코드의 일부 |
| 설정파일 | `claude_desktop_config.json` (제외) | `mcp_config.json` (포함) |

> 이 가이드는 **런타임 MCP** (P-Agent 내부 자체 서버)만 다룹니다.

---

## 2. P-Agent 내부 MCP 서버 구조

```
backend/app/
├── mcp_servers/                 ← 도구 서버들 (각각 독립 실행 가능)
│   ├── base_server.py           ← 모든 서버가 상속하는 베이스 클래스
│   ├── filesystem_server.py     ← 파일 읽기/쓰기/목록
│   ├── screen_server.py         ← 스크린샷/OCR/UI 요소 탐지
│   ├── automation_server.py     ← 마우스/키보드/브라우저 (⚠️ 승인 필요)
│   ├── rag_server.py            ← 사내 문서 검색
│   ├── report_server.py         ← Word/PPT 생성
│   └── mcp_config.json          ← 서버 등록 정보
│
└── mcp_client/
    ├── client.py                ← 서버 실행 + JSON-RPC 호출
    └── tool_registry.py         ← 모든 MCP 도구를 LangGraph tool로 자동 변환·등록
```

### 데이터 흐름
```
1. tool_registry 가 mcp_config.json 을 읽어 enabled=true 인 서버 목록 파악
2. 각 서버를 stdio 서브프로세스로 기동 → list_tools() 로 제공 도구 수집
3. 수집한 도구를 LangGraph 가 이해하는 tool 객체로 변환
4. Agent 가 tool 을 호출하면 → MCP Client 가 해당 서버에 call_tool 요청
5. 서버가 실행 결과를 JSON-RPC 응답으로 반환 → Agent 에 전달
```

### ⚠️ 도구 이름 규칙 (구현 시 반드시 지킬 것)

LLM API 는 도구 이름에 **`^[a-zA-Z0-9_-]{1,64}$` 만 허용**한다. **점(.)은 쓸 수 없다.**
따라서 P-Agent 는 두 가지 이름을 구분해서 사용한다.

| 용도 | 형식 | 예 |
|---|---|---|
| LLM 전달 / 내부 식별자 | `서버명__도구명` (밑줄 2개) | `filesystem__read_file` |
| 사용자 화면 표시 | `서버명.도구명` | `filesystem.read_file` |

변환은 `tool_registry.py` 의 `RegisteredTool.qualified_name` / `display_name` 이 담당하므로
도구를 추가할 때 신경 쓸 필요는 없다. 다만 **로그나 UI 에 표시할 때는 `display_name` 을 쓸 것.**

### 🔒 서버 프로세스 실행 방식 (포터블)

`mcp_config.json` 의 `"command": "python"` 은 실행 시 **현재 가상환경의 파이썬**
(`sys.executable`)으로 자동 치환된다. 시스템 PATH 에 어떤 python 이 있든 무관하게 동작한다.

또한 서버 프로세스에는 다음 환경변수가 강제로 주입된다.

| 환경변수 | 이유 |
|---|---|
| `PYTHONPATH=backend/` | `-m app.mcp_servers.xxx` 가 항상 해석되도록 |
| `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8` | **한글 Windows(cp949)에서 JSON-RPC 깨짐 방지** |
| `PYTHONDONTWRITEBYTECODE=1` | USB 에 `__pycache__` 를 남기지 않음 |

---

## 3. MCP 서버별 제공 도구 목록

**상태** 열: ✅ 구현 완료 / \* 선택 의존성·로컬 모델 필요

| 서버 | 도구 | 설명 | 승인 필요 | 상태 |
|---|---|---|:---:|:---:|
| **filesystem** | `read_file(path)` | 파일 읽기 (프로젝트 루트 하위로 제한) | — | ✅ |
| | `write_file(path, content)` | 파일 쓰기 | — | ✅ |
| | `list_dir(path)` | 디렉터리 목록 | — | ✅ |
| **screen** | `capture_screen(region)` | 화면 캡처 → PNG 저장 | — | ✅ |
| | `find_ui_element(description)` | 자연어로 UI 요소 위치 탐지 (OCR 기반) | — | ✅ * |
| | `ocr_region(bbox)` | 지정 영역 텍스트 인식 (PaddleOCR) | — | ✅ * |
| **automation** | `click(x, y)` | 마우스 클릭 | ✅ | ✅ |
| | `type_text(text)` | 텍스트 입력 | ✅ | ✅ |
| | `key_press(key)` | 키 입력 | ✅ | ✅ |
| | `open_browser(url)` | 브라우저 열기 (화이트리스트 검사) | ✅ | ✅ |
| **rag** | `search_internal_docs(query, top_k)` | 사내 문서 검색 (의미/키워드) | — | ✅ |
| | `add_document(path)` | 문서 색인 추가 | — | ✅ |
| **report** | `create_word_report(title, sections, citations)` | Word 보고서 생성 | — | ✅ |
| | `create_ppt_report(title, slides, citations)` | PPT 보고서 생성 | — | ✅ |

> ⚠️ **automation** 서버의 도구는 `require_approval: true` 로 지정되어,
> 실행 전 **Approval Gate**(사용자 승인)를 반드시 통과해야 합니다.
> 승인 콜백이 등록되어 있지 않으면 도구는 **실행되지 않고 차단**됩니다. (안전 우선 기본값)

> \* 표시된 도구는 **선택 의존성**(`uv sync --extra vision`)과 로컬 모델이 필요합니다.
> 설치되지 않았거나 화면이 없는 환경에서는 "왜 안 되는지 + 어떻게 해결하는지"를
> 한글로 안내하며 실패하고, 서버와 나머지 도구는 정상 동작합니다.

---

## 4. 🆕 새 도구 추가하는 방법

### 방법 A — 기존 서버에 도구 하나 추가

예: `filesystem_server.py`에 `delete_file` 추가.

1. **`get_tools()`** 에 도구 스키마를 추가합니다.
   ```python
   Tool(
       name="delete_file",
       description="지정한 파일을 삭제합니다 (프로젝트 루트 하위만 허용).",
       inputSchema={
           "type": "object",
           "properties": {"path": {"type": "string", "description": "삭제할 파일 경로"}},
           "required": ["path"],
       },
   )
   ```
2. **`handle_call()`** 에 실제 동작을 구현합니다.
   ```python
   if name == "delete_file":
       target = self._safe_path(arguments["path"])   # 경로 보안 검사
       target.unlink()
       return f"삭제 완료: {target}"
   ```
3. 끝! `tool_registry`가 다음 기동 시 자동으로 새 도구를 수집합니다.

### 방법 B — 새 도구 서버 통째로 추가

예: `email_server.py`(사내 메일 발송) 신규 추가.

1. `mcp_servers/email_server.py` 생성 후 `BaseMCPServer` 상속:
   ```python
   from app.mcp_servers.base_server import BaseMCPServer
   from mcp.types import Tool

   class EmailMCPServer(BaseMCPServer):
       def __init__(self):
           super().__init__("email")

       def get_tools(self) -> list[Tool]:
           return [Tool(name="send_mail", description="...", inputSchema={...})]

       async def handle_call(self, name: str, arguments: dict):
           if name == "send_mail":
               ...  # 실제 발송 로직
               return "발송 완료"

   if __name__ == "__main__":
       import asyncio
       asyncio.run(EmailMCPServer().run())
   ```
2. **`mcp_config.json`** 에 서버를 등록합니다:
   ```json
   "email": {
     "command": "python",
     "args": ["-m", "app.mcp_servers.email_server"],
     "enabled": true,
     "require_approval": true
   }
   ```
3. **테스트** 작성: `tests/test_mcp_servers.py`에 케이스 추가 후 실행.
4. 끝! Agent가 자동으로 `send_mail` 도구를 사용할 수 있게 됩니다.

---

## 5. 체크리스트 (새 도구 추가 시)

- [ ] `get_tools()`에 `name` / `description` / `inputSchema` 를 정확히 정의했는가?
- [ ] `handle_call()`에서 해당 `name`을 처리하는가?
- [ ] 파일/경로를 다룬다면 **프로젝트 루트 하위로 제한**했는가? (경로 탈출 방지)
- [ ] 위험한 동작이면 `require_approval: true` 로 등록했는가?
- [ ] `description`을 **Agent가 언제 이 도구를 쓸지 판단**할 수 있게 명확히 썼는가?
- [ ] 단독 실행 테스트(`test_mcp_servers.py`)를 통과하는가?
- [ ] 절대경로/시스템 환경변수에 의존하지 않는가? (포터블 원칙)

---

## 6. 단독 실행/디버깅

각 MCP 서버는 독립 프로세스이므로 단독으로 테스트할 수 있습니다.

```bash
# backend/ 디렉터리에서

# 1) 전체 서버 헬스체크 (가장 먼저 확인할 것)
python -m app.mcp_client --healthcheck

# 2) 전체 도구 자동 테스트 (실제 프로세스를 띄워 검증)
python -m pytest tests/test_mcp_servers.py -v

# 3) 서버 하나만 stdio 모드로 실행 (입력 대기 상태가 됨)
python -m app.mcp_servers.filesystem_server
```

헬스체크 정상 출력 예:
```
  [OK] filesystem   도구 3개
         - filesystem.read_file
  ...
  ✅ 정상: 서버 5개 / 도구 14개
```

> MCP 서버는 stdio 로 통신하므로 직접 실행하면 입력 대기 상태가 됩니다.
> 실제 호출 검증은 헬스체크나 `test_mcp_servers.py` 로 수행하세요.

### 🚫 서버 코드에서 절대 하면 안 되는 것

**`print()` 금지.** stdout 은 JSON-RPC 통신 전용이라 출력이 섞이면 통신이 깨집니다.
로그가 필요하면 반드시 `self.logger` (stderr 로 출력됨)를 사용하세요.

```python
# ❌ 통신이 깨집니다
print("파일 읽는 중...")

# ✅ 올바른 방법
self.logger.info("파일 읽는 중: %s", path)
```
