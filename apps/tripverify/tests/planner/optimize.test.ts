import { describe, it, expect } from "vitest";
import { clusterByDay, type Place } from "@/planner/cluster";
import { nearestNeighbor, twoOpt, optimizeOrder, pathCost, type Matrix } from "@/planner/tsp";
import { haversineMatrix } from "@/agents/fetchers/routing";
import { routeAgent } from "@/agents/route-agent";
import type { GeoPoint } from "@/core/types/domains";

describe("tsp 2-opt", () => {
  // 사각형 네 꼭짓점: 대각선으로 방문하면 손해, 둘레로 방문하면 이득.
  const P: GeoPoint[] = [
    { lat: 0, lng: 0 },
    { lat: 0, lng: 1 },
    { lat: 1, lng: 1 },
    { lat: 1, lng: 0 },
  ];
  function euclidMatrix(pts: GeoPoint[]): Matrix {
    return pts.map((a) => pts.map((b) => Math.hypot(a.lat - b.lat, a.lng - b.lng)));
  }

  it("2-opt 는 교차 경로를 개선한다", () => {
    const m = euclidMatrix(P);
    const bad = [0, 2, 1, 3]; // 대각선 교차
    const better = twoOpt(m, bad);
    expect(pathCost(m, better)).toBeLessThan(pathCost(m, bad));
  });

  it("optimizeOrder 는 시작점을 고정하고 순회를 반환한다", () => {
    const m = euclidMatrix(P);
    const order = optimizeOrder(m, 0);
    expect(order[0]).toBe(0);
    expect([...order].sort()).toEqual([0, 1, 2, 3]);
    expect(pathCost(m, order)).toBeLessThanOrEqual(pathCost(m, [0, 1, 2, 3]));
  });

  it("nearestNeighbor 는 모든 노드를 방문", () => {
    const m = euclidMatrix(P);
    expect([...nearestNeighbor(m, 0)].sort()).toEqual([0, 1, 2, 3]);
  });
});

describe("clusterByDay", () => {
  // 두 지역 뭉치(도쿄권/오사카권 흉내)
  const places: Place[] = [
    { id: "a1", location: { lat: 35.68, lng: 139.76 } },
    { id: "a2", location: { lat: 35.69, lng: 139.7 } },
    { id: "a3", location: { lat: 35.71, lng: 139.77 } },
    { id: "b1", location: { lat: 34.69, lng: 135.5 } },
    { id: "b2", location: { lat: 34.7, lng: 135.49 } },
    { id: "b3", location: { lat: 34.68, lng: 135.51 } },
  ];

  it("k=2 로 두 지역이 분리된다", () => {
    const clusters = clusterByDay(places, 2);
    expect(clusters.length).toBe(2);
    const all = clusters.flat().sort();
    expect(all).toEqual(["a1", "a2", "a3", "b1", "b2", "b3"]);
    // 각 군집이 하나의 지역으로만 구성되는지
    const groupOf = (id: string) => (id.startsWith("a") ? "a" : "b");
    for (const c of clusters) {
      const groups = new Set(c.map(groupOf));
      expect(groups.size).toBe(1);
    }
  });

  it("장소 수 <= k 면 빈 군집 없이 분배", () => {
    const clusters = clusterByDay(places.slice(0, 2), 5);
    expect(clusters.flat().length).toBe(2);
  });
});

describe("route-agent (해버사인 폴백)", () => {
  const places: Place[] = [
    { id: "p1", location: { lat: 34.69, lng: 135.5 } },
    { id: "p2", location: { lat: 34.7, lng: 135.52 } },
    { id: "p3", location: { lat: 34.68, lng: 135.49 } },
    { id: "p4", location: { lat: 34.66, lng: 135.55 } },
  ];

  it("일자별 순서와 총 소요시간을 산출(추정 라벨)", async () => {
    const plan = await routeAgent({ places, days: 2, mode: "transit" }, haversineMatrix);
    expect(plan.days.length).toBe(2);
    expect(plan.estimated).toBe(true);
    expect(plan.days.every((d) => d.total_travel_seconds >= 0)).toBe(true);
    const allIds = plan.days.flatMap((d) => d.ordered_place_ids).sort();
    expect(allIds).toEqual(["p1", "p2", "p3", "p4"]);
  });

  it("감수성: 전망(evening) 장소는 그날 마지막에 배치된다", async () => {
    const withPref: Place[] = [
      { id: "day1", location: { lat: 34.69, lng: 135.5 }, time_pref: "day" },
      { id: "tower", location: { lat: 34.7, lng: 135.51 }, time_pref: "evening" },
      { id: "day2", location: { lat: 34.68, lng: 135.49 }, time_pref: "day" },
    ];
    const plan = await routeAgent({ places: withPref, days: 1, mode: "transit" }, haversineMatrix);
    const order = plan.days[0]!.ordered_place_ids;
    expect(order[order.length - 1]).toBe("tower"); // 야경은 맨 끝
  });
});
