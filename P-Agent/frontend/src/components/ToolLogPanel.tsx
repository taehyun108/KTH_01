/**
 * MCP 도구 실행 로그 패널.
 *
 * 에이전트가 **어떤 도구를 호출했는지 실시간으로 보여준다.**
 * 사용자가 "지금 내 PC 에서 무슨 일이 일어나는지" 알 수 있어야
 * 자동화를 신뢰하고 사용할 수 있기 때문이다.
 */
import type { ToolLogEntry } from "../lib/api";

interface Props {
  entries: ToolLogEntry[];
}

/** 서버별 아이콘 (한눈에 구분되도록) */
const SERVER_ICONS: Record<string, string> = {
  filesystem: "📁",
  screen: "🖥️",
  automation: "🖱️",
  rag: "🔍",
  report: "📄",
};

function iconFor(tool: string): string {
  const server = tool.split(".")[0];
  return SERVER_ICONS[server] ?? "🔧";
}

export function ToolLogPanel({ entries }: Props) {
  return (
    <section className="panel tool-log">
      <h2>
        🔧 도구 실행 로그
        <span className="count">{entries.length}건</span>
      </h2>

      {entries.length === 0 ? (
        <p className="empty">아직 실행된 도구가 없습니다.</p>
      ) : (
        <ul>
          {entries.map((entry, index) => (
            <li key={index} className={entry.ok ? "ok" : "fail"}>
              <div className="tool-head">
                <span className="icon">{iconFor(entry.tool)}</span>
                <code className="tool-name">{entry.tool}</code>
                <span className="step">{entry.step}</span>
                <span className="result">{entry.ok ? "성공" : "실패"}</span>
              </div>
              <div className="tool-args">
                {JSON.stringify(entry.arguments).slice(0, 120)}
              </div>
              {entry.summary && (
                <div className="tool-summary">{entry.summary.slice(0, 200)}</div>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
