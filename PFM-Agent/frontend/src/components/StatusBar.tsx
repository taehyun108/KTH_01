/**
 * 상단 상태 표시줄.
 *
 * 사용 중인 LLM, 연결된 도구 서버, 비상 정지 키 상태를 보여준다.
 * 특히 **ESC 전역 단축키를 못 쓰는 환경**에서는 그 사실을 알려
 * 사용자가 화면의 정지 버튼을 쓰도록 안내한다.
 */
import type { ServerStatus } from "../lib/api";

interface Props {
  status: ServerStatus | null;
  error: string;
}

export function StatusBar({ status, error }: Props) {
  if (error) {
    return <div className="status-bar error">⚠️ {error}</div>;
  }

  if (!status) {
    return <div className="status-bar">백엔드에 연결하는 중…</div>;
  }

  const failedCount = Object.keys(status.mcp_failed).length;

  return (
    <div className="status-bar">
      <span className="chip">
        LLM <b>{status.llm_provider}</b>
        {status.llm_model && ` (${status.llm_model})`}
      </span>

      <span className="chip">
        도구 <b>{status.tools.length}</b>개 / 서버 {status.mcp_servers.length}개
        {failedCount > 0 && <span className="warn"> · 실패 {failedCount}</span>}
      </span>

      <span className={`chip ${status.kill_switch.global_hook_available ? "" : "warn"}`}>
        비상정지{" "}
        {status.kill_switch.global_hook_available
          ? `${status.kill_switch.key.toUpperCase()} 사용 가능`
          : "화면 버튼만 사용 가능"}
      </span>

      {status.require_approval && (
        <span className="chip">위험 작업 승인 필요</span>
      )}
    </div>
  );
}
