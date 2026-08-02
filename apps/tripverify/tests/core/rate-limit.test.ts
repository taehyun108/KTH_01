import { describe, it, expect, beforeEach } from "vitest";
import { rateLimit, __resetRateLimit } from "@/lib/rate-limit";

describe("rateLimit 슬라이딩 윈도우 (§8)", () => {
  beforeEach(() => __resetRateLimit());

  it("한도까지는 허용, 초과 시 차단 + retryAfter", () => {
    const t0 = 1_000_000;
    for (let i = 0; i < 3; i++) {
      expect(rateLimit("ip1", 3, 60_000, t0 + i).ok).toBe(true);
    }
    const blocked = rateLimit("ip1", 3, 60_000, t0 + 4);
    expect(blocked.ok).toBe(false);
    expect(blocked.retryAfterSec).toBeGreaterThan(0);
  });

  it("윈도우가 지나면 다시 허용", () => {
    const t0 = 2_000_000;
    for (let i = 0; i < 3; i++) rateLimit("ip2", 3, 60_000, t0 + i);
    expect(rateLimit("ip2", 3, 60_000, t0 + 61_000).ok).toBe(true);
  });

  it("키(IP)별로 독립적", () => {
    const t0 = 3_000_000;
    for (let i = 0; i < 3; i++) rateLimit("ipA", 3, 60_000, t0);
    expect(rateLimit("ipB", 3, 60_000, t0).ok).toBe(true);
  });
});
