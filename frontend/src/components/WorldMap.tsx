import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Canvas } from "@react-three/fiber";
import * as THREE from "three";
import type { Topic } from "../api";
import {
  buildTree,
  nodeAtPath,
  layoutStops,
  labelOf,
  type MapStop,
  type PlacedStop,
} from "../overworld/layout";
import OverworldScene from "../overworld/Scene";

/**
 * Animal Crossing–style 3D overworld.
 * Soft grass, dirt paths, log cabins, pine forests, cute walker.
 * WASD / arrows to walk · Enter to open · Esc to go back.
 */

type Keys = Record<string, boolean>;

export default function WorldMap({
  topics,
  renderCard,
  selectedTopicId,
  onSelectTopic,
}: {
  topics: Topic[];
  renderCard: (t: Topic) => ReactNode;
  selectedTopicId?: string | null;
  onSelectTopic?: (id: string | null) => void;
}) {
  const tree = useMemo(() => buildTree(topics), [topics]);
  const [navPath, setNavPath] = useState<string[]>([]);
  const [showPanel, setShowPanel] = useState(false);
  const [nearIndex, setNearIndex] = useState<number | null>(null);

  const keysRef = useRef<Keys>({});
  const autoWalkRef = useRef<{ x: number; z: number } | null>(null);
  const playerRef = useRef({ x: 0, z: 2 });

  const current = useMemo(() => nodeAtPath(tree, navPath), [tree, navPath]);
  const seed = navPath.join(">") || "overworld";

  const stops: MapStop[] = useMemo(() => {
    const list: MapStop[] = current.children.map((node) => ({
      kind: "world" as const,
      node,
      id: `world:${node.key}`,
    }));
    for (const topic of current.topics) {
      list.push({ kind: "level", topic, id: `level:${topic.id}` });
    }
    if (navPath.length === 0 && tree.topics.length > 0) {
      list.push({ kind: "ungrouped", topics: tree.topics, id: "ungrouped" });
    }
    return list;
  }, [current, navPath.length, tree.topics]);

  const { placed, edges } = useMemo(() => layoutStops(stops), [stops]);

  // Reset player when world changes
  useEffect(() => {
    if (placed.length > 0) {
      playerRef.current = { x: placed[0].x, z: placed[0].z + 2.4 };
    } else {
      playerRef.current = { x: 0, z: 2 };
    }
    setShowPanel(false);
    setNearIndex(null);
    onSelectTopic?.(null);
    autoWalkRef.current = null;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seed, placed.length]);

  const near: PlacedStop | null =
    nearIndex != null ? placed.find((p) => p.index === nearIndex) ?? null : null;

  const activateStop = useCallback(
    (p: PlacedStop) => {
      const stop = p.stop;
      if (stop.kind === "world") {
        setNavPath((prev) => [...prev, stop.node.name]);
        setShowPanel(false);
        onSelectTopic?.(null);
      } else if (stop.kind === "level") {
        setShowPanel(true);
        onSelectTopic?.(stop.topic.id);
      } else {
        setShowPanel(true);
        onSelectTopic?.(stop.topics[0]?.id ?? null);
      }
    },
    [onSelectTopic]
  );

  const enterNear = useCallback(() => {
    if (!near) return;
    activateStop(near);
  }, [near, activateStop]);

  const goBack = useCallback(() => {
    if (showPanel || selectedTopicId) {
      setShowPanel(false);
      onSelectTopic?.(null);
      return;
    }
    if (navPath.length === 0) return;
    setNavPath((p) => p.slice(0, -1));
  }, [navPath.length, onSelectTopic, selectedTopicId, showPanel]);

  const onActivateIndex = useCallback(
    (index: number) => {
      const p = placed.find((x) => x.index === index);
      if (!p) return;
      const dist = Math.hypot(
        p.x - playerRef.current.x,
        p.z - playerRef.current.z
      );
      if (dist < 1.5) {
        activateStop(p);
      } else {
        autoWalkRef.current = { x: p.x, z: p.z + 1.2 };
      }
    },
    [placed, activateStop]
  );

  // Keyboard
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if ((e.target as HTMLElement)?.isContentEditable) return;

      if (
        [
          "ArrowLeft",
          "ArrowRight",
          "ArrowUp",
          "ArrowDown",
          "a",
          "A",
          "d",
          "D",
          "w",
          "W",
          "s",
          "S",
        ].includes(e.key)
      ) {
        e.preventDefault();
        keysRef.current[e.key] = true;
        autoWalkRef.current = null;
      } else if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        enterNear();
      } else if (e.key === "Escape" || e.key === "Backspace") {
        e.preventDefault();
        goBack();
      }
    };
    const up = (e: KeyboardEvent) => {
      keysRef.current[e.key] = false;
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, [enterNear, goBack]);

  const panelTopics: Topic[] = useMemo(() => {
    if (!showPanel || !near) return [];
    if (near.stop.kind === "level") return [near.stop.topic];
    if (near.stop.kind === "ungrouped") return near.stop.topics;
    return [];
  }, [showPanel, near]);

  const breadcrumb =
    navPath.length === 0 ? "Overworld" : navPath.join("  →  ");

  // Minimap
  const miniW = 280;
  const miniH = 72;
  const sx = miniW / 28;
  const sy = miniH / 20;
  const [playerBlip, setPlayerBlip] = useState({ x: 0, z: 2 });
  useEffect(() => {
    const id = window.setInterval(() => {
      setPlayerBlip({ ...playerRef.current });
    }, 80);
    return () => window.clearInterval(id);
  }, []);

  return (
    <div className="world-map-root">
      {/* HUD */}
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <span className="ac-hud-title">
            {navPath.length === 0
              ? "☀ Overworld"
              : `🏡 ${current.name || "World"}`}
          </span>
          <span className="ac-hud-crumb">{breadcrumb}</span>
        </div>
        <div className="flex items-center gap-3">
          {navPath.length > 0 && (
            <button type="button" onClick={goBack} className="ac-btn">
              ← Map
            </button>
          )}
          <span className="hidden text-[11px] text-white/50 sm:inline">
            Drag orbit · Scroll zoom · WASD walk · Enter open
          </span>
        </div>
      </div>

      {/* 3D stage */}
      <div className="ac-stage">
        <Canvas
          shadows
          dpr={[1, 1.75]}
          camera={{
            position: [0.3, 10.5, 9.2],
            fov: 40,
            near: 0.1,
            far: 80,
          }}
          gl={{
            antialias: true,
            toneMapping: THREE.ACESFilmicToneMapping,
            toneMappingExposure: 1.08,
          }}
          onCreated={({ gl }) => {
            gl.setClearColor("#B8DCF0");
            gl.shadowMap.enabled = true;
            gl.shadowMap.type = THREE.PCFSoftShadowMap;
          }}
        >
          <OverworldScene
            placed={placed}
            edges={edges}
            seed={seed}
            keysRef={keysRef}
            autoWalkRef={autoWalkRef}
            playerRef={playerRef}
            onNearChange={setNearIndex}
            onActivate={onActivateIndex}
            nearIndex={nearIndex}
          />
        </Canvas>

        <div className="ac-corner-hud">
          <span className="ac-corner-world">
            {navPath.length === 0 ? "W★" : `W${navPath.length}`}
          </span>
          <span className="ac-corner-count">
            {placed.length} spot{placed.length === 1 ? "" : "s"}
          </span>
        </div>

        {placed.length === 0 && (
          <div className="ac-empty">
            <p>
              No spots on this island yet.
              <br />
              <span>Add topics with World &gt; Course &gt; Level</span>
            </p>
          </div>
        )}
      </div>

      {/* Minimap strip */}
      <div className="ac-minibar mt-3">
        <div className="ac-minibar-title">
          <span className="ac-minibar-name">
            {navPath.length === 0 ? "Overworld" : current.name || "World"}
          </span>
          <span className="ac-minibar-hint">
            walk to a cottage · Enter to go in
          </span>
        </div>
        <div className="ac-minimap" style={{ width: miniW, height: miniH }}>
          <svg width={miniW} height={miniH} viewBox={`0 0 ${miniW} ${miniH}`}>
            <rect width={miniW} height={miniH} fill="#8FBF6A" rx="4" />
            {edges.map((e, i) => {
              const A = placed[e.a];
              const B = placed[e.b];
              if (!A || !B) return null;
              return (
                <line
                  key={i}
                  x1={(A.x + 14) * sx}
                  y1={(A.z + 10) * sy}
                  x2={(B.x + 14) * sx}
                  y2={(B.z + 10) * sy}
                  stroke="#C4A06A"
                  strokeWidth="3"
                  strokeLinecap="round"
                />
              );
            })}
            {placed.map((p) => {
              const active = nearIndex === p.index;
              return (
                <circle
                  key={p.stop.id}
                  cx={(p.x + 14) * sx}
                  cy={(p.z + 10) * sy}
                  r={active ? 5 : 3.5}
                  fill={active ? "#F0C94A" : "#5B9CFF"}
                  stroke={active ? "#fff" : "#3A5A20"}
                  strokeWidth="1.2"
                />
              );
            })}
            <circle
              cx={(playerBlip.x + 14) * sx}
              cy={(playerBlip.z + 10) * sy}
              r={4.5}
              fill="#3D5FBF"
              stroke="#fff"
              strokeWidth="1.5"
            />
          </svg>
        </div>
      </div>

      {/* Level card panel */}
      {panelTopics.length > 0 && (
        <div className="level-panel mt-5">
          <div className="mb-3 flex items-center gap-2">
            <span className="inline-block h-3 w-3 rounded-full bg-[#5DCF7A] shadow-[0_0_0_3px_rgba(93,207,122,0.25)]" />
            <h3 className="text-sm font-semibold tracking-wide text-[#E8F5D8]">
              {near?.stop.kind === "ungrouped" ? "Loose levels" : "Level card"}
              {near ? ` · ${labelOf(near.stop)}` : ""}
            </h3>
          </div>
          <div className="flex flex-col gap-2">
            {panelTopics.map((t) => renderCard(t))}
          </div>
        </div>
      )}
    </div>
  );
}
