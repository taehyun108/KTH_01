"""
MCP 클라이언트 패키지 실행 진입점.

`python -m app.mcp_client --healthcheck` 형태로 실행한다.

(`python -m app.mcp_client.client` 로 직접 실행하면 패키지 __init__ 이 먼저
 모듈을 import 하기 때문에 runpy 경고가 발생한다. 이 파일을 두어 회피한다.)
"""

from __future__ import annotations

from app.mcp_client.client import main

if __name__ == "__main__":
    main()
