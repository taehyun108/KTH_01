"""
P-Agent MCP 클라이언트 패키지.

Agent 는 반드시 ToolRegistry 를 통해서만 도구를 호출한다. (직접 함수 호출 금지)
"""

from app.mcp_client.client import (
    MCPClient,
    MCPClientError,
    MCPServerConfig,
    MCPToolResult,
    load_mcp_config,
)
from app.mcp_client.tool_registry import (
    ApprovalDeniedError,
    RegisteredTool,
    ToolRegistry,
    split_qualified_name,
)

__all__ = [
    "ApprovalDeniedError",
    "MCPClient",
    "MCPClientError",
    "MCPServerConfig",
    "MCPToolResult",
    "RegisteredTool",
    "ToolRegistry",
    "load_mcp_config",
    "split_qualified_name",
]
