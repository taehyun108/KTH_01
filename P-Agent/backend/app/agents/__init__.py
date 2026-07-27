"""
P-Agent 6개 Agent 패키지.

Planner → Perception → Executor → Retriever → Verifier → Generator

⚠️ 모든 Agent 는 도구를 직접 호출하지 않고
   `runtime.call_tool()` (MCP 레지스트리 경유) 만 사용한다.
"""
