/**
 * TSP 근사 (§6): 최근접이웃 초기해 + 2-opt 개선.
 * 하루 동선 내부 방문 순서를 이동시간이 최소가 되도록 정렬한다.
 * 거리행렬(초 단위 소요시간)을 입력으로 받는다 — 직선거리 금지, 실 소요시간 사용.
 */

export type Matrix = number[][]; // durations[i][j]

/** 최근접이웃으로 초기 순회 경로 구성 (start 고정 가능). */
export function nearestNeighbor(matrix: Matrix, start = 0): number[] {
  const n = matrix.length;
  if (n === 0) return [];
  const visited = new Array<boolean>(n).fill(false);
  const path = [start];
  visited[start] = true;
  for (let step = 1; step < n; step++) {
    const last = path[path.length - 1]!;
    let best = -1;
    let bestD = Infinity;
    for (let j = 0; j < n; j++) {
      if (!visited[j] && matrix[last]![j]! < bestD) {
        bestD = matrix[last]![j]!;
        best = j;
      }
    }
    if (best === -1) break;
    visited[best] = true;
    path.push(best);
  }
  return path;
}

/** 경로 총 소요시간(초). 개방 경로(마지막→처음 복귀 없음) 기준. */
export function pathCost(matrix: Matrix, path: number[]): number {
  let sum = 0;
  for (let i = 0; i < path.length - 1; i++) sum += matrix[path[i]!]![path[i + 1]!]!;
  return sum;
}

/** 2-opt: 교차하는 구간을 뒤집어 개선. 개방 경로에서 start 인덱스는 고정. */
export function twoOpt(matrix: Matrix, initial: number[], fixStart = true): number[] {
  const path = [...initial];
  const n = path.length;
  if (n < 4) return path;
  let improved = true;
  const from = fixStart ? 1 : 0;
  while (improved) {
    improved = false;
    for (let i = from; i < n - 1; i++) {
      for (let k = i + 1; k < n; k++) {
        const delta = twoOptDelta(matrix, path, i, k);
        if (delta < -1e-9) {
          reverse(path, i, k);
          improved = true;
        }
      }
    }
  }
  return path;
}

function twoOptDelta(matrix: Matrix, path: number[], i: number, k: number): number {
  const a = path[i - 1]!;
  const b = path[i]!;
  const c = path[k]!;
  const d = path[k + 1];
  const removed = matrix[a]![b]! + (d !== undefined ? matrix[c]![d]! : 0);
  const added = matrix[a]![c]! + (d !== undefined ? matrix[b]![d]! : 0);
  return added - removed;
}

function reverse(path: number[], i: number, k: number): void {
  while (i < k) {
    [path[i], path[k]] = [path[k]!, path[i]!];
    i++;
    k--;
  }
}

/** 최근접이웃 + 2-opt 를 합친 최적화 진입점. 순서(인덱스 배열) 반환. */
export function optimizeOrder(matrix: Matrix, start = 0): number[] {
  return twoOpt(matrix, nearestNeighbor(matrix, start));
}
