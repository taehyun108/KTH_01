/**
 * PFM-Agent 메인 화면.
 *
 * 구성
 * ----
 *  - 왼쪽 : 채팅(요청 입력) + 진행 상황 + 결과
 *  - 오른쪽: MCP 도구 실행 로그 (지금 무슨 도구를 쓰는지 실시간 표시)
 *  - 상단 : 상태 표시줄 (LLM / 도구 / 비상정지)
 *  - 하단 : 비상 정지(Kill Switch) · 되돌리기 버튼
 *
 * 🔴 안전
 * ESC 키를 누르면 화면 어디서든 실행이 중단된다.
 * (전역 훅을 못 쓰는 환경에서도 앱 화면 안에서는 항상 동작한다)
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { ApprovalDialog } from "./components/ApprovalDialog";
import { StatusBar } from "./components/StatusBar";
import { ToolLogPanel } from "./components/ToolLogPanel";
import {
  ApiError,
  type AgentEvent,
  type RunDetail,
  type ServerStatus,
  type ToolLogEntry,
  fetchRun,
  fetchStatus,
  killRun,
  respondApproval,
  startRun,
  subscribeEvents,
  undoLast,
} from "./lib/api";

/** 예시 요청 (소듐이온배터리 시나리오) */
const EXAMPLE_REQUEST =
  "소듐이온배터리 관련 국내외 정책 동향을 조사해서 정부 부처 대응용 보고서를 작성해줘. " +
  "개요, 주요 내용, 시사점 순서로 정리하고 출처를 반드시 표기해줘.";

/** 진행 단계 표시 이름 */
const STEP_LABELS: Record<string, string> = {
  planner: "계획 수립",
  perception: "화면 인식",
  executor: "PC 조작",
  retriever: "자료 수집",
  verifier: "신뢰도 검증",
  generator: "보고서 작성",
};

interface PendingApproval {
  approvalId: string;
  tool: string;
  args: Record<string, unknown>;
}

export default function App() {
  const [status, setStatus] = useState<ServerStatus | null>(null);
  const [statusError, setStatusError] = useState("");

  const [message, setMessage] = useState("");
  const [runId, setRunId] = useState("");
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<string[]>([]);
  const [toolLog, setToolLog] = useState<ToolLogEntry[]>([]);
  const [result, setResult] = useState<RunDetail | null>(null);
  const [approval, setApproval] = useState<PendingApproval | null>(null);
  const [notice, setNotice] = useState("");

  const unsubscribeRef = useRef<(() => void) | null>(null);

  // ------------------------------------------------------------
  // 상태 조회
  // ------------------------------------------------------------
  const refreshStatus = useCallback(async () => {
    try {
      setStatus(await fetchStatus());
      setStatusError("");
    } catch (error) {
      setStatusError(
        error instanceof ApiError ? error.message : "백엔드 상태를 확인할 수 없습니다.",
      );
    }
  }, []);

  useEffect(() => {
    void refreshStatus();
    const timer = setInterval(() => void refreshStatus(), 10000);
    return () => clearInterval(timer);
  }, [refreshStatus]);

  // ------------------------------------------------------------
  // 비상 정지 (ESC)
  // ------------------------------------------------------------
  const handleKill = useCallback(async () => {
    try {
      await killRun(runId || undefined);
      setNotice("실행을 중단했습니다.");
      setRunning(false);
    } catch (error) {
      setNotice(
        error instanceof ApiError ? error.message : "중단 요청에 실패했습니다.",
      );
    }
  }, [runId]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        void handleKill();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [handleKill]);

  // ------------------------------------------------------------
  // 실행
  // ------------------------------------------------------------
  const handleEvent = useCallback((event: AgentEvent) => {
    const payload = event.payload;

    switch (event.type) {
      case "step_started": {
        const step = String(payload.step ?? "");
        const label = STEP_LABELS[step] ?? step;
        // 재검색 회차(2회차 이상)면 몇 번째인지 함께 보여준다.
        const iteration = Number(payload.iteration ?? 1);
        const suffix = iteration > 1 ? ` (${iteration}회차)` : "";
        setProgress((prev) => [...prev, `${label} 시작${suffix}`]);
        break;
      }
      case "retry_requested": {
        // 피드백 루프: 근거가 부족해 Retriever 로 되돌아간다.
        const queries = (payload.queries ?? []) as string[];
        setProgress((prev) => [
          ...prev,
          `근거가 부족해 다시 찾습니다 (신뢰도 ${String(payload.confidence ?? "")}점) ` +
            `→ 검색어: ${queries.join(", ")}`,
        ]);
        break;
      }
      case "tool_call": {
        setProgress((prev) => [...prev, `도구 호출: ${String(payload.tool ?? "")}`]);
        break;
      }
      case "tool_result": {
        setToolLog((prev) => [
          ...prev,
          {
            step: String(payload.step ?? ""),
            tool: String(payload.tool ?? ""),
            arguments: {},
            ok: Boolean(payload.ok),
            summary: String(payload.summary ?? ""),
          },
        ]);
        break;
      }
      case "approval_required": {
        setApproval({
          approvalId: String(payload.approval_id ?? ""),
          tool: String(payload.tool ?? ""),
          args: (payload.arguments ?? {}) as Record<string, unknown>,
        });
        break;
      }
      case "approval_resolved":
      case "approval_timeout": {
        setApproval(null);
        break;
      }
      case "privacy_masked": {
        setProgress((prev) => [
          ...prev,
          `개인정보 ${String(payload.count ?? "")}건을 가렸습니다`,
        ]);
        break;
      }
      case "run_killed": {
        setProgress((prev) => [...prev, "사용자가 실행을 중단했습니다"]);
        break;
      }
      case "run_finished": {
        setRunning(false);
        break;
      }
      default:
        break;
    }
  }, []);

  const handleSubmit = useCallback(async () => {
    const request = message.trim();
    if (!request || running) {
      return;
    }

    setRunning(true);
    setProgress([]);
    setToolLog([]);
    setResult(null);
    setNotice("");

    try {
      const { run_id } = await startRun(request);
      setRunId(run_id);

      unsubscribeRef.current?.();
      unsubscribeRef.current = subscribeEvents(run_id, handleEvent, setNotice);
    } catch (error) {
      setRunning(false);
      setNotice(
        error instanceof ApiError ? error.message : "실행을 시작하지 못했습니다.",
      );
    }
  }, [message, running, handleEvent]);

  // 실행이 끝나면 결과를 가져온다.
  useEffect(() => {
    if (running || !runId) {
      return;
    }
    void (async () => {
      try {
        setResult(await fetchRun(runId));
        await refreshStatus();
      } catch {
        // 결과 조회 실패는 화면에 이미 표시된 진행 상황으로 대체한다.
      }
    })();
  }, [running, runId, refreshStatus]);

  useEffect(() => () => unsubscribeRef.current?.(), []);

  // ------------------------------------------------------------
  // 승인 / 되돌리기
  // ------------------------------------------------------------
  const handleApproval = useCallback(
    async (approvalId: string, approved: boolean) => {
      setApproval(null);
      try {
        await respondApproval(approvalId, approved);
      } catch (error) {
        setNotice(
          error instanceof ApiError ? error.message : "승인 처리에 실패했습니다.",
        );
      }
    },
    [],
  );

  const handleUndo = useCallback(async () => {
    try {
      const { undone } = await undoLast(runId || undefined);
      setNotice(`되돌렸습니다: ${undone}`);
      await refreshStatus();
    } catch (error) {
      setNotice(
        error instanceof ApiError ? error.message : "되돌리기에 실패했습니다.",
      );
    }
  }, [runId, refreshStatus]);

  // ------------------------------------------------------------
  // 화면
  // ------------------------------------------------------------
  return (
    <div className="app">
      <header>
        <h1>🤖 PFM-Agent</h1>
        <StatusBar status={status} error={statusError} />
      </header>

      <main>
        <section className="panel chat">
          <h2>요청 입력</h2>

          <textarea
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            placeholder="하고 싶은 일을 자연어로 입력하세요. 예) 소듐이온배터리 정책동향 보고서를 만들어줘"
            rows={4}
            disabled={running}
          />

          <div className="chat-buttons">
            <button
              className="btn ghost"
              onClick={() => setMessage(EXAMPLE_REQUEST)}
              disabled={running}
            >
              예시 요청 넣기
            </button>
            <button
              className="btn primary"
              onClick={() => void handleSubmit()}
              disabled={running || !message.trim()}
            >
              {running ? "실행 중…" : "실행"}
            </button>
          </div>

          {notice && <p className="notice">{notice}</p>}

          <h2>진행 상황</h2>
          {progress.length === 0 ? (
            <p className="empty">아직 진행 중인 작업이 없습니다.</p>
          ) : (
            <ol className="progress">
              {progress.map((line, index) => (
                <li key={index}>{line}</li>
              ))}
            </ol>
          )}

          {result && (
            <div className="result">
              <h2>결과</h2>
              <p className="result-status">
                상태: <b>{result.status}</b> · 신뢰도 <b>{result.confidence}</b>점
                {/* 재검색이 일어났을 때만 회차를 표시한다. */}
                {result.iteration > 1 && (
                  <> · 자료 재검색 <b>{result.iteration}</b>회차</>
                )}
              </p>

              {result.tried_queries?.length > 1 && (
                <p className="result-queries">
                  🔍 시도한 검색어: {result.tried_queries.join(" / ")}
                </p>
              )}

              {result.report_path && (
                <p className="result-path">
                  📄 보고서: <code>{result.report_path}</code>
                </p>
              )}

              {result.plan.length > 0 && (
                <>
                  <h3>수립한 계획</h3>
                  <ol>
                    {result.plan.map((step, index) => (
                      <li key={index}>{step}</li>
                    ))}
                  </ol>
                </>
              )}

              {result.notes.length > 0 && (
                <>
                  <h3>참고 사항</h3>
                  <ul className="notes">
                    {result.notes.map((note, index) => (
                      <li key={index}>{note}</li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          )}
        </section>

        <ToolLogPanel entries={toolLog} />
      </main>

      <footer>
        <button className="btn danger big" onClick={() => void handleKill()}>
          🛑 비상 정지 (ESC)
        </button>
        <button
          className="btn"
          onClick={() => void handleUndo()}
          disabled={!status?.can_undo}
        >
          ↩️ 되돌리기
          {status?.can_undo && ` (${status.undo_stack.length})`}
        </button>
      </footer>

      {approval && (
        <ApprovalDialog
          approvalId={approval.approvalId}
          tool={approval.tool}
          args={approval.args}
          onRespond={(id, approved) => void handleApproval(id, approved)}
        />
      )}
    </div>
  );
}
