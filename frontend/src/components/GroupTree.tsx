import { useEffect, useMemo, useState, type ReactNode } from "react";
import type { Topic } from "../api";

/**
 * Finder-style collapsible tree derived from each topic's `path`.
 * Groups exist because topics claim them; collapse state persists in
 * localStorage. Cards render as full-width rows, top to bottom.
 */

interface TreeNode {
  name: string;
  key: string; // full path joined — unique and stable across renders
  children: TreeNode[];
  topics: Topic[];
  count: number; // topics in this whole subtree
  built: number; // built topics in this whole subtree
  reviewed: number; // reviewed topics in this whole subtree
}

function buildTree(topics: Topic[]): TreeNode {
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
        node.children.push(child); // insertion order = outline order
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

function collectKeys(node: TreeNode, acc: string[] = []): string[] {
  for (const c of node.children) {
    acc.push(c.key);
    collectKeys(c, acc);
  }
  return acc;
}

const LS_KEY = "conceptFactory.collapsedGroups";

/**
 * Progress readout: two clean bordered badges beside a group heading.
 *   • "X/Y Reviewed" — keeps a slim bar whose fill grows and shifts hue
 *     red → green as more of the subtree is signed off.
 *   • "X/Y Built" — a matching badge (no bar) for how many cards are built.
 * Y is the total card count, so an all-unbuilt group reads 0/Y.
 */
function ReviewBar({
  reviewed,
  count,
  built,
}: {
  reviewed: number;
  count: number;
  built: number;
}) {
  const frac = count > 0 ? reviewed / count : 0;
  const hue = Math.round(frac * 140); // 0 = red, 140 = green
  const fill = `hsl(${hue} 68% 47%)`;
  return (
    <span className="flex items-center gap-2">
      <span
        className="inline-flex items-center gap-2 rounded-full border border-emerald-400/25 bg-emerald-400/10 px-2.5 py-1"
        title={`${reviewed} of ${count} reviewed`}
      >
        <span className="font-mono text-[11px] font-medium tabular-nums text-emerald-200/90">
          {reviewed}/{count} Reviewed
        </span>
        <span className="h-1.5 w-14 overflow-hidden rounded-full bg-white/10">
          <span
            className="block h-full rounded-full transition-all duration-500"
            style={{ width: `${Math.round(frac * 100)}%`, backgroundColor: fill }}
          />
        </span>
      </span>
      <span
        className="inline-flex items-center rounded-full border border-sky-400/25 bg-sky-400/10 px-2.5 py-1"
        title={`${built} of ${count} built`}
      >
        <span className="font-mono text-[11px] font-medium tabular-nums text-sky-200/90">
          {built}/{count} Built
        </span>
      </span>
    </span>
  );
}

function Group({
  node,
  depth,
  collapsed,
  toggle,
  renderCard,
}: {
  node: TreeNode;
  depth: number;
  collapsed: Set<string>;
  toggle: (key: string) => void;
  renderCard: (t: Topic) => ReactNode;
}) {
  const isCollapsed = collapsed.has(node.key);
  return (
    <div className={depth > 0 ? "ml-[7px] border-l border-white/[0.07] pl-5" : ""}>
      <button
        onClick={() => toggle(node.key)}
        className="mb-2.5 mt-1 flex w-full items-baseline gap-2.5 text-left"
      >
        <span
          className={`inline-block translate-y-[-1px] text-[11px] text-slate-500 transition-transform ${
            isCollapsed ? "" : "rotate-90"
          }`}
          aria-hidden
        >
          ▶
        </span>
        <span
          className={`font-display font-semibold tracking-tight text-slate-100 ${
            depth === 0 ? "text-[1.15rem]" : depth === 1 ? "text-[1rem]" : "text-[0.9rem]"
          }`}
        >
          {node.name}
        </span>
        <ReviewBar reviewed={node.reviewed} count={node.count} built={node.built} />
      </button>

      {!isCollapsed && (
        <div className="mb-5 flex flex-col gap-4">
          {node.topics.length > 0 && (
            <div className="flex flex-col gap-2">{node.topics.map(renderCard)}</div>
          )}
          {node.children.map((child) => (
            <Group
              key={child.key}
              node={child}
              depth={depth + 1}
              collapsed={collapsed}
              toggle={toggle}
              renderCard={renderCard}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default function GroupTree({
  topics,
  renderCard,
}: {
  topics: Topic[];
  renderCard: (t: Topic) => ReactNode;
}) {
  const tree = useMemo(() => buildTree(topics), [topics]);

  const [collapsed, setCollapsed] = useState<Set<string>>(() => {
    try {
      return new Set<string>(JSON.parse(localStorage.getItem(LS_KEY) ?? "[]"));
    } catch {
      return new Set<string>();
    }
  });

  useEffect(() => {
    localStorage.setItem(LS_KEY, JSON.stringify([...collapsed]));
  }, [collapsed]);

  const toggle = (key: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });

  const ungrouped = tree.topics; // topics with path: []

  return (
    <div>
      <div className="mb-5 flex gap-4 font-mono text-[11px] text-slate-500">
        <button
          onClick={() => setCollapsed(new Set())}
          className="transition-colors hover:text-violet-300"
        >
          expand all
        </button>
        <button
          onClick={() => setCollapsed(new Set(collectKeys(tree)))}
          className="transition-colors hover:text-violet-300"
        >
          collapse all
        </button>
      </div>

      {tree.children.map((node) => (
        <Group
          key={node.key}
          node={node}
          depth={0}
          collapsed={collapsed}
          toggle={toggle}
          renderCard={renderCard}
        />
      ))}

      {ungrouped.length > 0 && (
        <div className="mt-8">
          <div className="mb-2.5 font-mono text-[11px] uppercase tracking-[0.15em] text-slate-500">
            Ungrouped · {ungrouped.length}
          </div>
          <div className="flex flex-col gap-2">{ungrouped.map(renderCard)}</div>
        </div>
      )}
    </div>
  );
}
