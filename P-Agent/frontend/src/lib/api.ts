/**
 * P-Agent 백엔드 API 클라이언트.
 *
 * ⚠️ 포터블 원칙
 * 백엔드 주소를 하드코딩하지 않고, 개발 시에는 Vite 환경변수를,
 * 배포(Tauri) 시에는 같은 호스트의 기본 포트를 사용한다.
 */

/** 백엔드 기본 주소 */
export const API_BASE: string =
  import.meta.env.VITE_BACKEND_URL ?? "http://127.0.0.1:8756";

/** 실행 상태 */
export type RunStatus = "running" | "completed" | "killed" | "error";

/** 도구 호출 기록 한 건 */
export interface ToolLogEntry {
  step: string;
  tool: string;
  arguments: Record<string, unknown>;
  ok: boolean;
  summary: string;
}

/** 실행 상세 정보 */
export interface RunDetail {
  run_id: string;
  user_request: string;
  status: RunStatus;
  started_at: string;
  finished_at: string;
  plan: string[];
  confidence: number;
  verification: string;
  report_path: string;
  summary: string;
  notes: string[];
  tool_log: ToolLogEntry[];
  error: string;
}

/** 등록된 MCP 도구 */
export interface ToolInfo {
  name: string;
  server: string;
  require_approval: boolean;
  description: string;
}

/** Kill Switch 상태 */
export interface KillSwitchStatus {
  key: string;
  global_hook_available: boolean;
  reason: string;
  trigger_count: number;
}

/** 서버 상태 */
export interface ServerStatus {
  ready: boolean;
  startup_error: string;
  llm_provider: string;
  llm_model: string;
  require_approval: boolean;
  kill_switch_key: string;
  kill_switch: KillSwitchStatus;
  can_undo: boolean;
  undo_stack: { description: string; created_at: string }[];
  mcp_servers: string[];
  mcp_failed: Record<string, string>;
  tools: ToolInfo[];
}

/** 실시간 이벤트 */
export interface AgentEvent {
  run_id: string;
  type: string;
  payload: Record<string, unknown>;
  timestamp: string;
}

/** API 오류 (사용자에게 그대로 보여줄 수 있는 한글 메시지) */
export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/**
 * 백엔드에 요청을 보낸다.
 *
 * 오류 응답의 detail 을 그대로 사용해 한글 안내가 사용자에게 전달되게 한다.
 */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch {
    throw new ApiError(
      "백엔드에 연결할 수 없습니다. run_all.bat 로 프로그램을 실행했는지 확인하세요.",
      0,
    );
  }

  if (!response.ok) {
    let detail = `요청이 실패했습니다 (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") {
        detail = body.detail;
      }
    } catch {
      // JSON 이 아니면 기본 메시지를 쓴다.
    }
    throw new ApiError(detail, response.status);
  }

  return (await response.json()) as T;
}

/** 서버/도구 상태를 조회한다. */
export function fetchStatus(): Promise<ServerStatus> {
  return request<ServerStatus>("/api/status");
}

/** 새 실행을 시작한다. */
export function startRun(message: string): Promise<{ run_id: string }> {
  return request("/api/agent/run", {
    method: "POST",
    body: JSON.stringify({ message }),
  });
}

/** 실행 상세를 조회한다. */
export function fetchRun(runId: string): Promise<RunDetail> {
  return request<RunDetail>(`/api/agent/run/${runId}`);
}

/** 위험 도구 실행을 승인하거나 거절한다. */
export function respondApproval(
  approvalId: string,
  approved: boolean,
): Promise<unknown> {
  return request("/api/agent/approve", {
    method: "POST",
    body: JSON.stringify({ approval_id: approvalId, approved }),
  });
}

/** 실행을 중단한다. runId 를 생략하면 모든 실행을 중단한다. */
export function killRun(runId?: string): Promise<unknown> {
  return request("/api/agent/kill", {
    method: "POST",
    body: JSON.stringify({ run_id: runId ?? null }),
  });
}

/** 가장 최근 작업을 되돌린다. */
export function undoLast(runId?: string): Promise<{ undone: string }> {
  return request("/api/agent/undo", {
    method: "POST",
    body: JSON.stringify({ run_id: runId ?? null }),
  });
}

/**
 * 실행 진행 상황을 WebSocket 으로 구독한다.
 *
 * @returns 구독 해제 함수
 */
export function subscribeEvents(
  runId: string,
  onEvent: (event: AgentEvent) => void,
  onError?: (message: string) => void,
): () => void {
  const wsBase = API_BASE.replace(/^http/, "ws");
  const socket = new WebSocket(`${wsBase}/ws/agent/${runId}`);

  socket.onmessage = (message) => {
    try {
      onEvent(JSON.parse(message.data) as AgentEvent);
    } catch {
      // 형식이 깨진 메시지는 무시한다.
    }
  };

  socket.onerror = () => {
    onError?.("실시간 연결이 끊어졌습니다. 진행 상황이 갱신되지 않을 수 있습니다.");
  };

  return () => {
    if (
      socket.readyState === WebSocket.OPEN ||
      socket.readyState === WebSocket.CONNECTING
    ) {
      socket.close();
    }
  };
}
