/**
 * 승인 요청 대화상자 (Human-in-the-loop).
 *
 * 마우스/키보드 조작 같은 위험한 도구는 이 창에서 승인해야 실행된다.
 * ⚠️ 응답하지 않으면 자동으로 거절된다. (안전 우선)
 */
interface Props {
  approvalId: string;
  tool: string;
  args: Record<string, unknown>;
  onRespond: (approvalId: string, approved: boolean) => void;
}

export function ApprovalDialog({ approvalId, tool, args, onRespond }: Props) {
  return (
    <div className="approval-overlay" role="dialog" aria-modal="true">
      <div className="approval-box">
        <h2>⚠️ 실행 승인이 필요합니다</h2>

        <p className="approval-desc">
          에이전트가 아래 작업을 하려고 합니다. 확인 후 결정해 주세요.
        </p>

        <div className="approval-detail">
          <div className="row">
            <span className="label">도구</span>
            <code>{tool}</code>
          </div>
          <div className="row">
            <span className="label">내용</span>
            <pre>{JSON.stringify(args, null, 2)}</pre>
          </div>
        </div>

        <p className="approval-warn">
          이 작업은 실제로 PC 를 조작합니다. 예상과 다르면 <b>거절</b>하세요.
        </p>

        <div className="approval-buttons">
          <button className="btn danger" onClick={() => onRespond(approvalId, false)}>
            거절
          </button>
          <button className="btn primary" onClick={() => onRespond(approvalId, true)}>
            승인하고 실행
          </button>
        </div>
      </div>
    </div>
  );
}
