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
import { usePolling } from "../hooks/usePolling";
import {
  buildTree,
  nodeAtPath,
  layoutStops,
  labelOf,
  WORLD_W,
  WORLD_D,
  type MapStop,
  type PlacedStop,
} from "../overworld/layout";
import OverworldScene from "../overworld/Scene";

/**
 * 3D overworld — a cozy island diorama.
 * Every group is a house, every topic a cottage; walk between them.
 * WASD / arrows to walk · Enter to open · Esc to go back.
 * All chrome lives inside the stage as a game HUD.
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
      playerRef.current = { x: placed[0].x, z: placed[0].z + 2.0 };
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

  const regionTitle = navPath.length === 0 ? "Overworld" : current.name || "World";
  const breadcrumb =
    navPath.length === 0
      ? `${placed.length} stop${placed.length === 1 ? "" : "s"} on the island`
      : ["Overworld", ...navPath].join(" › ");

  // Progress for the current region (root shows the whole library).
  const regionBuilt = navPath.length === 0 ? tree.built : current.built;
  const regionCount = navPath.length === 0 ? tree.count : current.count;
  const regionPct =
    regionCount > 0 ? Math.round((regionBuilt / regionCount) * 100) : 0;

  // Minimap — true world aspect (WORLD_W × WORLD_D plus a margin).
  const PAD = 3;
  const mapW = WORLD_W + PAD * 2;
  const mapD = WORLD_D + PAD * 2;
  const miniW = 172;
  const miniH = Math.round((miniW * mapD) / mapW);
  const mx = (x: number) => ((x + WORLD_W / 2 + PAD) / mapW) * miniW;
  const mz = (z: number) => ((z + WORLD_D / 2 + PAD) / mapD) * miniH;
  const [playerBlip, setPlayerBlip] = useState({ x: 0, z: 2 });
  usePolling(() => setPlayerBlip({ ...playerRef.current }), 80);

  return (
    <div className="world-map-root">
      {/* 3D stage + in-game HUD */}
      <div className="ac-stage">
        <Canvas
          shadows
          dpr={[1, 1.75]}
          camera={{
            position: [0.3, 10.5, 9.2],
            fov: 40,
            near: 0.1,
            far: 120,
          }}
          gl={{
            antialias: true,
            toneMapping: THREE.ACESFilmicToneMapping,
            toneMappingExposure: 1.05,
          }}
          onCreated={({ gl }) => {
            gl.setClearColor("#8ec4e8");
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

        {/* Location plate */}
        <div className="hud-plate">
          <span className="hud-plate-eyebrow">
            {navPath.length === 0
              ? "Region · Overworld"
              : navPath.length === 1
                ? "Region · World"
                : "Region · Course"}
          </span>
          <span className="hud-plate-title">{regionTitle}</span>
          <span className="hud-plate-sub">{breadcrumb}</span>
        </div>

        {/* Region progress */}
        {regionCount > 0 && (
          <div className="hud-progress" title={`${regionBuilt} of ${regionCount} concepts built`}>
            <span className="hud-progress-bar">
              <span
                className="hud-progress-fill"
                style={{ width: `${regionPct}%`, display: "block" }}
              />
            </span>
            {regionBuilt}/{regionCount} built
          </div>
        )}

        {/* Back — only when inside a world or a panel is open */}
        {(navPath.length > 0 || showPanel) && (
          <button type="button" onClick={goBack} className="hud-back">
            ← {showPanel ? "Close" : "Back"}
            <span className="kbd">esc</span>
          </button>
        )}

        {/* Controls */}
        <div className="hud-keys">
          <span className="hud-key-group">
            <span className="kbd">W</span>
            <span className="kbd">A</span>
            <span className="kbd">S</span>
            <span className="kbd">D</span>
            walk
          </span>
          <span className="hud-key-group">
            <span className="kbd">↵</span>
            enter
          </span>
          <span className="hud-key-group hidden sm:flex">
            <span className="kbd">drag</span>
            orbit
          </span>
          <span className="hud-key-group hidden sm:flex">
            <span className="kbd">scroll</span>
            zoom
          </span>
        </div>

        {/* Minimap */}
        <div className="hud-minimap" style={{ width: miniW, height: miniH }}>
          <svg width={miniW} height={miniH} viewBox={`0 0 ${miniW} ${miniH}`}>
            <rect width={miniW} height={miniH} fill="rgba(13,23,20,0.55)" />
            <rect
              x={mx(-WORLD_W / 2)}
              y={mz(-WORLD_D / 2)}
              width={mx(WORLD_W / 2) - mx(-WORLD_W / 2)}
              height={mz(WORLD_D / 2) - mz(-WORLD_D / 2)}
              rx={10}
              fill="rgba(96,160,90,0.35)"
              stroke="rgba(150,210,140,0.35)"
              strokeWidth="1"
            />
            {edges.map((e, i) => {
              const A = placed[e.a];
              const B = placed[e.b];
              if (!A || !B) return null;
              return (
                <line
                  key={i}
                  x1={mx(A.x)}
                  y1={mz(A.z)}
                  x2={mx(B.x)}
                  y2={mz(B.z)}
                  stroke="rgba(222,190,140,0.5)"
                  strokeWidth="2"
                  strokeLinecap="round"
                />
              );
            })}
            {placed.map((p) => {
              const active = nearIndex === p.index;
              return (
                <circle
                  key={p.stop.id}
                  cx={mx(p.x)}
                  cy={mz(p.z)}
                  r={active ? 4 : 2.8}
                  fill={active ? "#fbbf24" : "#e2e8f0"}
                  stroke={active ? "#fff" : "rgba(255,255,255,0.4)"}
                  strokeWidth="1"
                />
              );
            })}
            <circle
              cx={mx(playerBlip.x)}
              cy={mz(playerBlip.z)}
              r={4}
              fill="#34d399"
              stroke="#052e1b"
              strokeWidth="1.5"
            />
          </svg>
        </div>

        {placed.length === 0 && (
          <div className="ac-empty">
            <p>
              No stops on this island yet.
              <br />
              <span>Add topics with World &gt; Course &gt; Level</span>
            </p>
          </div>
        )}
      </div>

      {/* Level card panel */}
      {panelTopics.length > 0 && (
        <div className="level-panel mt-5">
          <div className="mb-3 flex items-center gap-2">
            <span className="inline-block h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_0_3px_rgba(52,211,153,0.2)]" />
            <h3 className="font-display text-[13.5px] font-semibold tracking-tight text-slate-100">
              {near?.stop.kind === "ungrouped" ? "Loose levels" : "Level"}
              {near ? (
                <span className="font-normal text-slate-400">
                  {" "}
                  · {labelOf(near.stop)}
                </span>
              ) : null}
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
