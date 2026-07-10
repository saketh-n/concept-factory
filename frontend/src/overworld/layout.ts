import type { Topic } from "../api";

export interface TreeNode {
  name: string;
  key: string;
  children: TreeNode[];
  topics: Topic[];
  count: number;
  built: number;
  reviewed: number;
}

export type MapStop =
  | { kind: "world"; node: TreeNode; id: string }
  | { kind: "level"; topic: Topic; id: string }
  | { kind: "ungrouped"; topics: Topic[]; id: string };

export interface PlacedStop {
  stop: MapStop;
  /** World X (east) */
  x: number;
  /** World Z (south) */
  z: number;
  index: number;
}

export interface Edge {
  a: number;
  b: number;
}

/** World extents (XZ ground plane). */
export const WORLD_W = 28;
export const WORLD_D = 20;
export const ENTER_DIST = 1.7;
export const MOVE_SPEED = 5.0;

export function hash01(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0) / 4294967296;
}

export function buildTree(topics: Topic[]): TreeNode {
  const root: TreeNode = {
    name: "",
    key: "",
    children: [],
    topics: [],
    count: 0,
    built: 0,
    reviewed: 0,
  };
  for (const t of topics) {
    let node = root;
    for (const part of t.path ?? []) {
      let child = node.children.find((c) => c.name === part);
      if (!child) {
        child = {
          name: part,
          key: node.key ? `${node.key} > ${part}` : part,
          children: [],
          topics: [],
          count: 0,
          built: 0,
          reviewed: 0,
        };
        node.children.push(child);
      }
      node = child;
    }
    node.topics.push(t);
  }
  const tally = (n: TreeNode): [number, number, number] => {
    let count = n.topics.length;
    let built = n.topics.filter((t) => t.planStatus === "built").length;
    let reviewed = n.topics.filter((t) => t.reviewed).length;
    for (const c of n.children) {
      const [cc, cb, cr] = tally(c);
      count += cc;
      built += cb;
      reviewed += cr;
    }
    n.count = count;
    n.built = built;
    n.reviewed = reviewed;
    return [count, built, reviewed];
  };
  tally(root);
  return root;
}

export function nodeAtPath(root: TreeNode, path: string[]): TreeNode {
  let node = root;
  for (const part of path) {
    const next = node.children.find((c) => c.name === part);
    if (!next) return node;
    node = next;
  }
  return node;
}

export function labelOf(stop: MapStop): string {
  if (stop.kind === "world") return stop.node.name;
  if (stop.kind === "level") return stop.topic.title || "Untitled";
  return `Loose levels (${stop.topics.length})`;
}

/**
 * Place stops in world XZ (centered on origin).
 * Coordinates map old 960×560 layout into WORLD_W × WORLD_D.
 */
export function layoutStops(stops: MapStop[]): {
  placed: PlacedStop[];
  edges: Edge[];
} {
  const n = stops.length;
  if (n === 0) return { placed: [], edges: [] };

  const halfW = WORLD_W * 0.38;
  const halfD = WORLD_D * 0.34;

  const special: { x: number; z: number }[] | null = (() => {
    if (n === 1) return [{ x: 0, z: 0 }];
    if (n === 2)
      return [
        { x: -halfW * 0.55, z: -halfD * 0.15 },
        { x: halfW * 0.55, z: halfD * 0.15 },
      ];
    if (n === 3)
      return [
        { x: -halfW * 0.65, z: halfD * 0.1 },
        { x: 0, z: -halfD * 0.55 },
        { x: halfW * 0.65, z: halfD * 0.15 },
      ];
    if (n === 4)
      return [
        { x: -halfW * 0.55, z: -halfD * 0.4 },
        { x: halfW * 0.5, z: -halfD * 0.35 },
        { x: -halfW * 0.4, z: halfD * 0.45 },
        { x: halfW * 0.55, z: halfD * 0.4 },
      ];
    if (n === 5)
      return [
        { x: 0, z: -halfD * 0.6 },
        { x: -halfW * 0.65, z: -halfD * 0.05 },
        { x: halfW * 0.65, z: 0 },
        { x: -halfW * 0.4, z: halfD * 0.55 },
        { x: halfW * 0.45, z: halfD * 0.5 },
      ];
    return null;
  })();

  let placed: PlacedStop[];
  let cols = 1;
  let rows = 1;

  if (special) {
    placed = stops.map((stop, i) => {
      const jx = (hash01(stop.id + "x") - 0.5) * 1.2;
      const jz = (hash01(stop.id + "z") - 0.5) * 1.0;
      return {
        stop,
        x: special[i].x + jx,
        z: special[i].z + jz,
        index: i,
      };
    });
  } else {
    cols = Math.max(3, Math.min(5, Math.ceil(Math.sqrt(n * 1.5))));
    rows = Math.max(2, Math.ceil(n / cols));
    cols = Math.max(3, Math.ceil(n / rows));
    const usableW = halfW * 2;
    const usableD = halfD * 2;

    placed = stops.map((stop, i) => {
      const row = Math.floor(i / cols);
      const colInRow = i % cols;
      const col = row % 2 === 0 ? colInRow : cols - 1 - colInRow;
      const cellW = usableW / Math.max(cols - 1, 1);
      const cellD = usableD / Math.max(rows - 1, 1);
      const jx = (hash01(stop.id + "x") - 0.5) * Math.min(cellW * 0.3, 1.4);
      const jz = (hash01(stop.id + "z") - 0.5) * Math.min(cellD * 0.3, 1.2);
      return {
        stop,
        x: -halfW + col * cellW + jx,
        z: -halfD + row * cellD + jz,
        index: i,
      };
    });
  }

  const edges: Edge[] = [];
  for (let i = 0; i < n - 1; i++) edges.push({ a: i, b: i + 1 });
  if (n >= 3 && n <= 6) edges.push({ a: n - 1, b: 0 });

  if (!special) {
    for (let i = 0; i < n; i++) {
      const row = Math.floor(i / cols);
      const colInRow = i % cols;
      const col = row % 2 === 0 ? colInRow : cols - 1 - colInRow;
      if (row < rows - 1) {
        const nextRow = row + 1;
        const nextColInRow = nextRow % 2 === 0 ? col : cols - 1 - col;
        const j = nextRow * cols + nextColInRow;
        if (j < n && Math.abs(j - i) > 1 && hash01(stops[i].id + "branch") > 0.4) {
          edges.push({ a: i, b: j });
        }
      }
    }
  } else if (n >= 4) {
    edges.push({ a: 0, b: Math.min(2, n - 1) });
    if (n >= 5) edges.push({ a: 1, b: Math.min(3, n - 1) });
  }

  return { placed, edges };
}

/** Sample a soft elbow/curve path between two world points (XZ). */
export function pathSamples(
  ax: number,
  az: number,
  bx: number,
  bz: number,
  seed: string,
  segments = 28
): { x: number; z: number }[] {
  // Soft quadratic Bezier with a sideways mid control — AC dirt paths meander
  const midBias = (hash01(seed) - 0.5) * 0.55;
  const mx = (ax + bx) / 2 + (bz - az) * midBias * 0.35;
  const mz = (az + bz) / 2 + (ax - bx) * midBias * 0.35;
  const pts: { x: number; z: number }[] = [];
  for (let i = 0; i <= segments; i++) {
    const t = i / segments;
    const x = (1 - t) * (1 - t) * ax + 2 * (1 - t) * t * mx + t * t * bx;
    const z = (1 - t) * (1 - t) * az + 2 * (1 - t) * t * mz + t * t * bz;
    pts.push({ x, z });
  }
  return pts;
}

export function padColor(stop: MapStop): string {
  if (stop.kind === "world") return "#5B9CFF";
  if (stop.kind === "ungrouped") return "#F0C94A";
  const s = stop.topic.planStatus;
  if (s === "built") return stop.topic.reviewed ? "#5DCF7A" : "#E85D5D";
  if (s === "ready") return "#B07AE0";
  if (s === "planning" || s === "building") return "#F0A03A";
  if (s === "error") return "#C94444";
  return "#5B9CFF";
}
