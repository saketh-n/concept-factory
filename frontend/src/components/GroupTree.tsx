import { useEffect, useMemo, useState, type ReactNode } from "react";
import type { Topic } from "../api";
import { IconChevronRight } from "./icons";

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
  const done = frac >= 1;
  return (
    <span className="flex items-center gap-3" onClick={(e) => e.stopPropagation()}>
      <span
        className="inline-flex items-center gap-2"
        title={`${reviewed} of ${count} reviewed`}
      >
        <span className="h-1 w-16 overflow-hidden rounded-full bg-white/[0.08]">
          <span
            className={`block h-full rounded-full transition-all duration-500 ${
              done ? "bg-emerald-400" : "bg-amber-400"
            }`}
            style={{ width: `${Math.round(frac * 100)}%` }}
          />
        </span>
        <span className="font-mono text-[10.5px] font-medium tabular-nums text-slate-500">
          {reviewed}/{count} reviewed
        </span>
      </span>
      <span
        className="font-mono text-[10.5px] font-medium tabular-nums text-slate-500"
        title={`${built} of ${count} built`}
      >
        {built}/{count} built
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
    <div className={depth > 0 ? "ml-[13px] border-l border-white/[0.06] pl-5" : ""}>
      <button
        onClick={() => toggle(node.key)}
        className="group/header mb-2.5 mt-1 flex w-full items-center gap-2.5 rounded-lg px-1 py-0.5 text-left transition-colors hover:bg-white/[0.02]"
      >
        <span
          className={`inline-flex text-slate-500 transition-transform group-hover/header:text-slate-300 ${
            isCollapsed ? "" : "rotate-90"
          }`}
          aria-hidden
        >
          <IconChevronRight size={13} />
        </span>
        <span
          className={`font-display font-semibold tracking-tight text-slate-100 ${
            depth === 0 ? "text-[1.05rem]" : depth === 1 ? "text-[0.95rem]" : "text-[0.875rem]"
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
      <div className="mb-4 flex gap-1">
        <button onClick={() => setCollapsed(new Set())} className="btn-ghost !text-[11.5px]">
          Expand all
        </button>
        <button
          onClick={() => setCollapsed(new Set(collectKeys(tree)))}
          className="btn-ghost !text-[11.5px]"
        >
          Collapse all
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
