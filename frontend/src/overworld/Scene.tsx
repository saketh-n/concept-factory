import { useEffect, useMemo, useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";
import { Html, SoftShadows } from "@react-three/drei";
import {
  EffectComposer,
  Bloom,
  Vignette,
  SMAA,
  HueSaturation,
  BrightnessContrast,
} from "@react-three/postprocessing";
import {
  type Edge,
  type PlacedStop,
  ENTER_DIST,
  MOVE_SPEED,
  WORLD_D,
  WORLD_W,
  pathSamples,
  padColor,
  labelOf,
} from "./layout";
import RogueCharacter from "./PlayerCharacter";
import {
  ACCottage,
  ACHouse,
  ACMystery,
  Boulders,
  Butterflies,
  Clouds,
  DirtPath,
  type Exclusion,
  ForestBelt,
  GrassBlades,
  GrassField,
  Island,
  LampPost,
  Ocean,
  RedGrass,
  SkyDome,
  SunGlow,
  Vista,
} from "./props";

type Keys = Record<string, boolean>;

interface Props {
  placed: PlacedStop[];
  edges: Edge[];
  seed: string;
  keysRef: React.MutableRefObject<Keys>;
  autoWalkRef: React.MutableRefObject<{ x: number; z: number } | null>;
  playerRef: React.MutableRefObject<{ x: number; z: number }>;
  onNearChange: (index: number | null) => void;
  onActivate: (index: number) => void;
  nearIndex: number | null;
}

/** Default spherical camera: slightly south, elevated — diorama view. */
const CAM_PHI_DEFAULT = 0.92; // polar angle from Y-up (0 = top-down)
const CAM_THETA_DEFAULT = 0.04; // azimuth
const CAM_RADIUS_DEFAULT = 14.5;
const CAM_RADIUS_MIN = 6;
const CAM_RADIUS_MAX = 26;
const CAM_PHI_MIN = 0.35; // almost top-down
const CAM_PHI_MAX = 1.22; // more side-on, still above horizon

/**
 * Follows the player while allowing orbit rotate + scroll zoom.
 * - Drag: orbit
 * - Scroll / pinch: zoom
 * - Click without drag: still walks (handled by GroundClick via dragGuard)
 */
function CameraRig({
  target,
  dragGuard,
}: {
  target: React.MutableRefObject<{ x: number; z: number }>;
  dragGuard: React.MutableRefObject<boolean>;
}) {
  const { gl, camera } = useThree();
  const smooth = useRef(new THREE.Vector3(0, 0, 0));
  const spherical = useRef({
    theta: CAM_THETA_DEFAULT,
    phi: CAM_PHI_DEFAULT,
    radius: CAM_RADIUS_DEFAULT,
  });
  const dragging = useRef(false);
  const moved = useRef(false);
  const lastPtr = useRef({ x: 0, y: 0 });
  // Optional keyboard orbit (Q/E rotate, +/- zoom)
  const keysHeld = useRef<Record<string, boolean>>({});

  useEffect(() => {
    const el = gl.domElement;
    el.style.touchAction = "none";

    const onDown = (e: PointerEvent) => {
      if (e.button !== 0 && e.button !== 1 && e.button !== 2) return;
      dragging.current = true;
      moved.current = false;
      dragGuard.current = false;
      lastPtr.current = { x: e.clientX, y: e.clientY };
      try {
        el.setPointerCapture(e.pointerId);
      } catch {
        /* ignore */
      }
    };

    const onMove = (e: PointerEvent) => {
      if (!dragging.current) return;
      const dx = e.clientX - lastPtr.current.x;
      const dy = e.clientY - lastPtr.current.y;
      if (!moved.current && Math.hypot(dx, dy) > 3) {
        moved.current = true;
        dragGuard.current = true; // suppress ground-click walk
      }
      if (!moved.current) return;
      lastPtr.current = { x: e.clientX, y: e.clientY };

      const sens = 0.0055;
      spherical.current.theta -= dx * sens;
      spherical.current.phi = THREE.MathUtils.clamp(
        spherical.current.phi + dy * sens,
        CAM_PHI_MIN,
        CAM_PHI_MAX
      );
    };

    const onUp = (e: PointerEvent) => {
      dragging.current = false;
      if (moved.current) {
        // leave guard set briefly so click is ignored
        window.setTimeout(() => {
          dragGuard.current = false;
          moved.current = false;
        }, 40);
      } else {
        dragGuard.current = false;
      }
      try {
        el.releasePointerCapture(e.pointerId);
      } catch {
        /* ignore */
      }
    };

    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const delta = e.deltaY;
      const step = Math.sign(delta) * Math.min(Math.abs(delta) * 0.02, 1.8);
      spherical.current.radius = THREE.MathUtils.clamp(
        spherical.current.radius + step,
        CAM_RADIUS_MIN,
        CAM_RADIUS_MAX
      );
    };

    const onContext = (e: Event) => e.preventDefault();

    const onKeyDown = (e: KeyboardEvent) => {
      keysHeld.current[e.key] = true;
    };
    const onKeyUp = (e: KeyboardEvent) => {
      keysHeld.current[e.key] = false;
    };

    el.addEventListener("pointerdown", onDown);
    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerup", onUp);
    el.addEventListener("pointercancel", onUp);
    el.addEventListener("wheel", onWheel, { passive: false });
    el.addEventListener("contextmenu", onContext);
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);

    return () => {
      el.removeEventListener("pointerdown", onDown);
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerup", onUp);
      el.removeEventListener("pointercancel", onUp);
      el.removeEventListener("wheel", onWheel);
      el.removeEventListener("contextmenu", onContext);
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
    };
  }, [gl, dragGuard]);

  useFrame((_, dt) => {
    const k = keysHeld.current;
    const rotSpeed = 1.4 * dt;
    const zoomSpeed = 8 * dt;
    if (k.q || k.Q) spherical.current.theta += rotSpeed;
    if (k.e || k.E) spherical.current.theta -= rotSpeed;
    if (k["="] || k["+"] || k.PageUp) {
      spherical.current.radius = THREE.MathUtils.clamp(
        spherical.current.radius - zoomSpeed,
        CAM_RADIUS_MIN,
        CAM_RADIUS_MAX
      );
    }
    if (k["-"] || k["_"] || k.PageDown) {
      spherical.current.radius = THREE.MathUtils.clamp(
        spherical.current.radius + zoomSpeed,
        CAM_RADIUS_MIN,
        CAM_RADIUS_MAX
      );
    }

    const goal = new THREE.Vector3(target.current.x, 0.35, target.current.z);
    smooth.current.lerp(goal, 1 - Math.exp(-dt * 3.5));

    const { theta, phi, radius } = spherical.current;
    const sinPhi = Math.sin(phi);
    const offset = new THREE.Vector3(
      radius * sinPhi * Math.sin(theta),
      radius * Math.cos(phi),
      radius * sinPhi * Math.cos(theta)
    );

    camera.position.copy(smooth.current).add(offset);
    camera.lookAt(smooth.current);
  });

  return null;
}

function GroundClick({
  autoWalkRef,
  dragGuard,
}: {
  autoWalkRef: React.MutableRefObject<{ x: number; z: number } | null>;
  dragGuard: React.MutableRefObject<boolean>;
}) {
  return (
    <mesh
      rotation={[-Math.PI / 2, 0, 0]}
      position={[0, 0.012, 0]}
      onClick={(e) => {
        if (dragGuard.current) return; // was a camera orbit drag
        e.stopPropagation();
        autoWalkRef.current = { x: e.point.x, z: e.point.z };
      }}
    >
      <planeGeometry args={[WORLD_W + 10, WORLD_D + 10]} />
      <meshBasicMaterial transparent opacity={0} depthWrite={false} />
    </mesh>
  );
}

function hashRot(id: string) {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) | 0;
  return (((h >>> 0) % 100) / 100 - 0.5) * 0.5;
}

function StopLandmark({
  placed,
  near,
  onActivate,
}: {
  placed: PlacedStop;
  near: boolean;
  onActivate: () => void;
}) {
  const stop = placed.stop;
  const color = padColor(stop);
  const label = labelOf(stop);
  const isCastle =
    stop.kind === "world" &&
    (stop.node.children.length > 0 || stop.node.count > 3);
  const scale = isCastle ? 1.18 : 1;
  const ringRef = useRef<THREE.Mesh>(null);

  useFrame((state) => {
    if (ringRef.current) {
      const t = state.clock.elapsedTime;
      const s = 1 + Math.sin(t * 3.2) * 0.05;
      ringRef.current.scale.set(s, s, 1);
    }
  });

  return (
    <group
      position={[placed.x, 0, placed.z]}
      scale={scale}
      onClick={(e) => {
        e.stopPropagation();
        onActivate();
      }}
    >
      {stop.kind === "world" && (
        <ACHouse
          position={[0, 0, 0]}
          accent={color}
          rotation={hashRot(stop.id)}
          glow
        />
      )}
      {stop.kind === "level" && (
        <ACCottage
          position={[0, 0, 0]}
          color={color}
          built={stop.topic.planStatus === "built"}
        />
      )}
      {stop.kind === "ungrouped" && <ACMystery position={[0, 0, 0]} />}

      {near && (
        <mesh
          ref={ringRef}
          position={[0, 0.05, 0]}
          rotation={[-Math.PI / 2, 0, 0]}
        >
          <ringGeometry args={[0.8, 1.05, 40]} />
          <meshStandardMaterial
            color="#6ee7b7"
            emissive="#6ee7b7"
            emissiveIntensity={1.1}
            transparent
            opacity={0.85}
            roughness={0.4}
          />
        </mesh>
      )}

      {/* Fixed screen-size label — game POI style, never balloons up close */}
      <Html
        position={[0, stop.kind === "world" ? 2.55 : 1.35, 0]}
        center
        style={{ pointerEvents: "none", userSelect: "none" }}
        zIndexRange={[4, 0]}
      >
        <div className="ac-label">
          <div className="ac-label-title">{label}</div>
          {stop.kind === "world" && (
            <div className="ac-label-meta">
              {stop.node.built}/{stop.node.count}
            </div>
          )}
          {near && (
            <div className="ac-label-hint">
              {stop.kind === "world" ? "enter ↵" : "open ↵"}
            </div>
          )}
        </div>
      </Html>
    </group>
  );
}

/** Player mutates its group each frame — no React re-renders. */
function LivePlayer({
  keysRef,
  autoWalkRef,
  playerRef,
  placed,
  onNearChange,
}: {
  keysRef: React.MutableRefObject<Keys>;
  autoWalkRef: React.MutableRefObject<{ x: number; z: number } | null>;
  playerRef: React.MutableRefObject<{ x: number; z: number }>;
  placed: PlacedStop[];
  onNearChange: (index: number | null) => void;
}) {
  const group = useRef<THREE.Group>(null);
  const body = useRef<THREE.Group>(null);
  const facing = useRef(0);
  const walking = useRef(false);
  const nearRef = useRef<number | null>(null);

  useFrame((_, dt) => {
    if (!group.current) return;
    const k = keysRef.current;
    let dx = 0;
    let dz = 0;
    if (k.ArrowLeft || k.a || k.A) dx -= 1;
    if (k.ArrowRight || k.d || k.D) dx += 1;
    if (k.ArrowUp || k.w || k.W) dz -= 1;
    if (k.ArrowDown || k.s || k.S) dz += 1;

    const auto = autoWalkRef.current;
    if (auto && dx === 0 && dz === 0) {
      const adx = auto.x - group.current.position.x;
      const adz = auto.z - group.current.position.z;
      const dist = Math.hypot(adx, adz);
      if (dist < 0.12) autoWalkRef.current = null;
      else {
        dx = adx / dist;
        dz = adz / dist;
      }
    }

    if (dx !== 0 || dz !== 0) {
      const len = Math.hypot(dx, dz) || 1;
      dx = (dx / len) * MOVE_SPEED * dt;
      dz = (dz / len) * MOVE_SPEED * dt;
      facing.current = Math.atan2(dx, dz);
      walking.current = true;
      group.current.position.x = THREE.MathUtils.clamp(
        group.current.position.x + dx,
        -WORLD_W / 2 - 1.5,
        WORLD_W / 2 + 1.5
      );
      group.current.position.z = THREE.MathUtils.clamp(
        group.current.position.z + dz,
        -WORLD_D / 2 - 1.5,
        WORLD_D / 2 + 1.5
      );
    } else {
      walking.current = false;
    }

    playerRef.current = {
      x: group.current.position.x,
      z: group.current.position.z,
    };

    // Face the direction of travel; the animation clips handle all body motion.
    if (body.current) {
      const cur = body.current.rotation.y;
      let diff = facing.current - cur;
      while (diff > Math.PI) diff -= Math.PI * 2;
      while (diff < -Math.PI) diff += Math.PI * 2;
      body.current.rotation.y = cur + diff * Math.min(1, dt * 12);
    }

    let best: number | null = null;
    let bestD = ENTER_DIST;
    const px = group.current.position.x;
    const pz = group.current.position.z;
    for (const p of placed) {
      const d = Math.hypot(p.x - px, p.z - pz);
      if (d < bestD) {
        bestD = d;
        best = p.index;
      }
    }
    if (best !== nearRef.current) {
      nearRef.current = best;
      onNearChange(best);
    }
  });

  useEffect(() => {
    if (group.current) {
      group.current.position.set(playerRef.current.x, 0, playerRef.current.z);
    }
    // New world, new stops — forget the old near-index or a same-index stop
    // in the next world would never re-announce itself.
    nearRef.current = null;
  }, [placed, playerRef]);

  return (
    <group ref={group} position={[playerRef.current.x, 0, playerRef.current.z]}>
      {/* soft contact shadow to ground the character */}
      <mesh position={[0, 0.02, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <circleGeometry args={[0.34, 16]} />
        <meshStandardMaterial color="#000" transparent opacity={0.18} roughness={1} />
      </mesh>
      <group ref={body}>
        <RogueCharacter movingRef={walking} speed={MOVE_SPEED} />
      </group>
    </group>
  );
}

export default function OverworldScene({
  placed,
  edges,
  seed,
  keysRef,
  autoWalkRef,
  playerRef,
  onNearChange,
  onActivate,
  nearIndex,
}: Props) {
  const dragGuard = useRef(false);

  const paths = useMemo(() => {
    return edges
      .map((e) => {
        const A = placed[e.a];
        const B = placed[e.b];
        if (!A || !B) return null;
        return pathSamples(A.x, A.z, B.x, B.z, `${A.stop.id}-${B.stop.id}`, 26);
      })
      .filter(Boolean) as { x: number; z: number }[][];
  }, [edges, placed]);

  // One lamp per path, ~38% along, nudged off the trail.
  const lamps = useMemo(() => {
    return paths
      .filter((_, i) => i % 2 === 0)
      .map((pts) => {
        const i = Math.floor(pts.length * 0.38);
        const p = pts[i];
        const q = pts[Math.min(i + 1, pts.length - 1)];
        let nx = -(q.z - p.z);
        let nz = q.x - p.x;
        const len = Math.hypot(nx, nz) || 1;
        nx /= len;
        nz /= len;
        return { x: p.x + nx * 1.05, z: p.z + nz * 1.05 };
      });
  }, [paths]);

  // Ground-cover punch-outs so grass/boulders/red-grass never spawn on top
  // of stops, dirt paths, or lamp posts. Stops get a wider pad so large
  // field stones never bury the player near a landmark.
  const exclusions = useMemo<Exclusion[]>(() => {
    const out: Exclusion[] = [];
    for (const p of placed) out.push({ x: p.x, z: p.z, r: 2.6 });
    for (const pts of paths) {
      for (let i = 0; i < pts.length; i += 3) {
        out.push({ x: pts[i].x, z: pts[i].z, r: 0.95 });
      }
    }
    for (const l of lamps) out.push({ x: l.x, z: l.z, r: 1.2 });
    return out;
  }, [placed, paths, lamps]);

  return (
    <>
      {/* Soft atmospheric haze — keeps distant hills/trees reading as depth */}
      <fog attach="fog" args={["#c8e0ee", 28, 78]} />

      <ambientLight intensity={0.48} color="#fff6e8" />
      <hemisphereLight args={["#b8d8f5", "#6aab48", 0.72]} />
      {/* Golden key sun — BOTW meadow warmth */}
      <directionalLight
        castShadow
        position={[14, 22, 10]}
        intensity={1.85}
        color="#ffe2a8"
        shadow-mapSize={[2048, 2048]}
        shadow-camera-far={60}
        shadow-camera-left={-24}
        shadow-camera-right={24}
        shadow-camera-top={24}
        shadow-camera-bottom={-24}
        shadow-bias={-0.00025}
      />
      {/* Cool sky fill */}
      <directionalLight position={[-10, 12, -8]} intensity={0.38} color="#a0c4ff" />
      {/* Soft rim from behind the camera */}
      <directionalLight position={[2, 6, 14]} intensity={0.22} color="#fff0d0" />

      <SoftShadows size={18} samples={16} focus={0.55} />

      <CameraRig target={playerRef} dragGuard={dragGuard} />

      <SkyDome />
      <SunGlow />
      <Clouds />
      <Vista />
      <Ocean />
      <Island />
      <GrassField />
      <Boulders exclusions={exclusions} seed={seed} />
      <ForestBelt seed={seed} />
      <GrassBlades exclusions={exclusions} seed={seed} />
      <RedGrass exclusions={exclusions} seed={seed} />
      <Butterflies seed={seed} />

      {paths.map((pts, i) => (
        <DirtPath key={i} points={pts} width={1.2} />
      ))}
      {lamps.map((l, i) => (
        <LampPost key={i} position={[l.x, 0, l.z]} />
      ))}

      {placed.map((p) => (
        <StopLandmark
          key={p.stop.id}
          placed={p}
          near={nearIndex === p.index}
          onActivate={() => onActivate(p.index)}
        />
      ))}

      <LivePlayer
        keysRef={keysRef}
        autoWalkRef={autoWalkRef}
        playerRef={playerRef}
        placed={placed}
        onNearChange={onNearChange}
      />

      <GroundClick autoWalkRef={autoWalkRef} dragGuard={dragGuard} />

      <EffectComposer multisampling={0}>
        <SMAA />
        <Bloom
          intensity={0.42}
          luminanceThreshold={0.82}
          luminanceSmoothing={0.28}
          mipmapBlur
        />
        <BrightnessContrast brightness={0.02} contrast={0.08} />
        <HueSaturation saturation={0.22} />
        <Vignette eskil={false} offset={0.12} darkness={0.28} />
      </EffectComposer>
    </>
  );
}
