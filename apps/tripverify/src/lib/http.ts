import "server-only";
import { ProxyAgent, Agent, setGlobalDispatcher } from "undici";

/**
 * 프록시 인지 HTTP 계층.
 * 이 실행 환경의 아웃바운드 HTTPS 는 HTTPS_PROXY 를 경유한다. Node 의 전역 fetch(undici)
 * 는 프록시 환경변수를 자동 인식하지 않으므로 전역 디스패처를 명시적으로 설정한다.
 * TLS 신뢰는 NODE_EXTRA_CA_CERTS(프록시 CA 번들)로 이미 구성되어 있다.
 */
let configured = false;
function ensureDispatcher(): void {
  if (configured) return;
  const proxy = process.env.HTTPS_PROXY ?? process.env.https_proxy;
  if (proxy) {
    setGlobalDispatcher(new ProxyAgent({ uri: proxy }));
  } else {
    setGlobalDispatcher(new Agent());
  }
  configured = true;
}

export interface FetchJsonOptions {
  timeoutMs?: number;
  headers?: Record<string, string>;
}

/** JSON GET. 실패 시 throw. retrieved_at 은 호출부에서 기록. */
export async function fetchJson<T = unknown>(
  url: string,
  opts: FetchJsonOptions = {},
): Promise<T> {
  ensureDispatcher();
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), opts.timeoutMs ?? 12_000);
  try {
    const res = await fetch(url, {
      signal: ctrl.signal,
      headers: {
        accept: "application/json",
        "user-agent": "TripVerify/0.1 (+https://github.com/taehyun108/kth_01)",
        ...opts.headers,
      },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status} for ${url}`);
    return (await res.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

export function nowISO(): string {
  return new Date().toISOString();
}
