import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import { hash01, WORLD_W, WORLD_D } from "./layout";

/* ── Palette — warm, saturated, game-grade ─────────────────────────── */
export const AC = {
  grass: "#7db95c",
  grassDark: "#639a48",
  grassLight: "#94cc70",
  cliff: "#8a6a48",
  cliffDark: "#6e5238",
  sand: "#e8d5a4",
  ocean: "#3d87c4",
  oceanDeep: "#2e6ea6",
  foam: "#eaf6ff",
  dirtPath: "#c9a26e",
  dirtEdge: "#a67f4e",
  canopyDeep: "#2e7f3c",
  canopyMid: "#43a04a",
  canopyLite: "#63c05e",
  canopyTip: "#85d878",
  trunk: "#6b4423",
  log: "#c8a076",
  logDark: "#a5805a",
  logLite: "#e0c8a0",
  roof: "#3d7a5c",
  roofDark: "#2a5a42",
  roofLite: "#4f9a72",
  windowGlow: "#ffd98a",
  windowFrame: "#7a5c1e",
  door: "#7a4a28",
  mailbox: "#e07040",
  sky: "#8ec4e8",
  fog: "#b9dcf0",
  playerBody: "#3d5fbf",
  playerDark: "#2a4490",
  playerFeet: "#e05050",
  playerFace: "#f5c8a0",
  flowerY: "#f7e05a",
  flowerP: "#f090b8",
  flowerB: "#8fb8f0",
  flowerR: "#ef6a5a",
  stone: "#a8a294",
} as const;

/** Soft matte material helper — surfaces are matte, slightly toon. */
function mat(color: string, opts?: { roughness?: number; metalness?: number }) {
  return (
    <meshStandardMaterial
      color={color}
      roughness={opts?.roughness ?? 0.88}
      metalness={opts?.metalness ?? 0.02}
    />
  );
}

/* ── Shared geometry helpers ───────────────────────────────────────── */
function roundedRectShape(w: number, h: number, r: number) {
  const s = new THREE.Shape();
  const x = -w / 2;
  const y = -h / 2;
  s.moveTo(x, y + r);
  s.lineTo(x, y + h - r);
  s.quadraticCurveTo(x, y + h, x + r, y + h);
  s.lineTo(x + w - r, y + h);
  s.quadraticCurveTo(x + w, y + h, x + w, y + h - r);
  s.lineTo(x + w, y + r);
  s.quadraticCurveTo(x + w, y, x + w - r, y);
  s.lineTo(x + r, y);
  s.quadraticCurveTo(x, y, x, y + r);
  return s;
}

/** Island footprint (grass plateau) half-extents beyond the play area. */
export const ISLAND_MARGIN = 4.2;
const ISL_W = WORLD_W + ISLAND_MARGIN * 2;
const ISL_D = WORLD_D + ISLAND_MARGIN * 2;
const ISL_R = 7;
const SEA_Y = -1.42;

/* ── Sky dome — vertical gradient, sits behind everything ──────────── */
export function SkyDome() {
  const material = useMemo(() => {
    return new THREE.ShaderMaterial({
      side: THREE.BackSide,
      depthWrite: false,
      fog: false,
      uniforms: {
        top: { value: new THREE.Color("#5ea7dd") },
        horizon: { value: new THREE.Color("#cfe9f7") },
      },
      vertexShader: /* glsl */ `
        varying vec3 vPos;
        void main() {
          vPos = position;
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        }
      `,
      fragmentShader: /* glsl */ `
        uniform vec3 top;
        uniform vec3 horizon;
        varying vec3 vPos;
        void main() {
          float h = clamp(normalize(vPos).y * 1.6 + 0.18, 0.0, 1.0);
          gl_FragColor = vec4(mix(horizon, top, pow(h, 0.8)), 1.0);
        }
      `,
    });
  }, []);
  return (
    <mesh material={material} renderOrder={-10}>
      <sphereGeometry args={[95, 24, 16]} />
    </mesh>
  );
}

/* ── Drifting billboard clouds ─────────────────────────────────────── */
function cloudTexture(): THREE.Texture {
  const size = 256;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size / 2;
  const ctx = canvas.getContext("2d")!;
  const blobs = [
    [70, 78, 44],
    [120, 62, 52],
    [172, 76, 46],
    [96, 88, 36],
    [148, 90, 40],
    [200, 92, 30],
  ];
  for (const [x, y, r] of blobs) {
    const g = ctx.createRadialGradient(x, y, 2, x, y, r);
    g.addColorStop(0, "rgba(255,255,255,0.92)");
    g.addColorStop(0.65, "rgba(255,255,255,0.5)");
    g.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, size, size / 2);
  }
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

export function Clouds() {
  const tex = useMemo(cloudTexture, []);
  const group = useRef<THREE.Group>(null);
  const clouds = useMemo(
    () =>
      Array.from({ length: 8 }, (_, i) => ({
        x: (hash01("cx" + i) - 0.5) * 120,
        y: 15 + hash01("cy" + i) * 9,
        z: -18 - hash01("cz" + i) * 34,
        s: 9 + hash01("cs" + i) * 10,
        v: 0.25 + hash01("cv" + i) * 0.35,
        o: 0.5 + hash01("co" + i) * 0.35,
      })),
    []
  );

  useFrame((_, dt) => {
    if (!group.current) return;
    group.current.children.forEach((c, i) => {
      c.position.x += clouds[i].v * dt;
      if (c.position.x > 70) c.position.x = -70;
    });
  });

  return (
    <group ref={group}>
      {clouds.map((c, i) => (
        <sprite key={i} position={[c.x, c.y, c.z]} scale={[c.s, c.s * 0.5, 1]}>
          <spriteMaterial
            map={tex}
            transparent
            opacity={c.o}
            depthWrite={false}
            fog={false}
          />
        </sprite>
      ))}
    </group>
  );
}

/* ── Ocean with animated shimmer + foam ring around the island ─────── */
function oceanTexture(): THREE.Texture {
  const size = 256;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d")!;
  ctx.fillStyle = "#4a9ad8";
  ctx.fillRect(0, 0, size, size);
  // layered sine "waves" — light streaks
  for (let i = 0; i < 260; i++) {
    const x = hash01("ox" + i) * size;
    const y = hash01("oy" + i) * size;
    const w = 6 + hash01("ow" + i) * 22;
    const light = hash01("ol" + i) > 0.4;
    ctx.fillStyle = light
      ? `rgba(255,255,255,${0.07 + hash01("oa" + i) * 0.1})`
      : `rgba(40,90,150,${0.05 + hash01("ob" + i) * 0.07})`;
    ctx.beginPath();
    ctx.ellipse(x, y, w, 1.6 + hash01("oh" + i) * 2.2, 0, 0, Math.PI * 2);
    ctx.fill();
  }
  const tex = new THREE.CanvasTexture(canvas);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.repeat.set(7, 7);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

export function Ocean() {
  const tex = useMemo(oceanTexture, []);
  const mref = useRef<THREE.MeshStandardMaterial>(null);
  useFrame((state) => {
    const t = state.clock.elapsedTime;
    tex.offset.set(t * 0.006, t * 0.004);
  });

  // Foam collar hugging the beach
  const foamGeo = useMemo(() => {
    const outer = roundedRectShape(ISL_W + 4.6, ISL_D + 4.6, ISL_R + 2.2);
    const inner = roundedRectShape(ISL_W + 1.2, ISL_D + 1.2, ISL_R + 0.8);
    outer.holes.push(new THREE.Path(inner.getPoints(48).reverse()));
    return new THREE.ShapeGeometry(outer, 48);
  }, []);
  const foamRef = useRef<THREE.MeshBasicMaterial>(null);
  useFrame((state) => {
    if (foamRef.current)
      foamRef.current.opacity =
        0.28 + Math.sin(state.clock.elapsedTime * 0.9) * 0.1;
  });

  return (
    <group>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, SEA_Y, 0]}>
        <planeGeometry args={[260, 260]} />
        <meshStandardMaterial
          ref={mref}
          map={tex}
          color="#dceefc"
          roughness={0.42}
          metalness={0.05}
        />
      </mesh>
      <mesh
        geometry={foamGeo}
        rotation={[-Math.PI / 2, 0, 0]}
        position={[0, SEA_Y + 0.015, 0]}
      >
        <meshBasicMaterial
          ref={foamRef}
          color={AC.foam}
          transparent
          opacity={0.42}
          depthWrite={false}
        />
      </mesh>
    </group>
  );
}

/* ── Island: cliff walls + sand beach + grass top ──────────────────── */
function grassTexture(): THREE.Texture {
  const size = 256;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d")!;
  ctx.fillStyle = AC.grass;
  ctx.fillRect(0, 0, size, size);
  // multi-scale mottling
  for (let i = 0; i < 900; i++) {
    const x = hash01("gx" + i) * size;
    const y = hash01("gy" + i) * size;
    const r = 1 + hash01("gr" + i) * 3.4;
    const l = hash01("gl" + i);
    ctx.fillStyle =
      l > 0.66
        ? `rgba(178,220,132,${0.10 + l * 0.12})`
        : l > 0.33
          ? `rgba(96,150,66,${0.10 + l * 0.10})`
          : `rgba(70,120,52,${0.08 + l * 0.10})`;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
  }
  // fine speckle
  for (let i = 0; i < 1600; i++) {
    const x = hash01("sx" + i) * size;
    const y = hash01("sy" + i) * size;
    ctx.fillStyle =
      hash01("sl" + i) > 0.5 ? "rgba(200,235,150,0.16)" : "rgba(60,105,45,0.14)";
    ctx.fillRect(x, y, 1.4, 1.4);
  }
  const tex = new THREE.CanvasTexture(canvas);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.repeat.set(9, 7);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 4;
  return tex;
}

export function Island() {
  const grassTex = useMemo(grassTexture, []);

  const topGeo = useMemo(
    () => new THREE.ShapeGeometry(roundedRectShape(ISL_W, ISL_D, ISL_R), 48),
    []
  );
  const cliffGeo = useMemo(() => {
    const shape = roundedRectShape(ISL_W, ISL_D, ISL_R);
    // No bevel: a bevel would rise above the grass cap and swallow it.
    const g = new THREE.ExtrudeGeometry(shape, {
      depth: 2.0,
      bevelEnabled: false,
      curveSegments: 40,
    });
    return g;
  }, []);
  const beachGeo = useMemo(
    () =>
      new THREE.ShapeGeometry(
        roundedRectShape(ISL_W + 2.4, ISL_D + 2.4, ISL_R + 1.2),
        48
      ),
    []
  );

  return (
    <group>
      {/* sand shelf just above the water */}
      <mesh
        geometry={beachGeo}
        rotation={[-Math.PI / 2, 0, 0]}
        position={[0, SEA_Y + 0.06, 0]}
        receiveShadow
      >
        {mat(AC.sand, { roughness: 0.95 })}
      </mesh>

      {/* cliff body (extruded down from the plateau) */}
      <mesh geometry={cliffGeo} rotation={[Math.PI / 2, 0, 0]} position={[0, -0.05, 0]}>
        {mat(AC.cliff, { roughness: 0.95 })}
      </mesh>

      {/* grass cap */}
      <mesh
        geometry={topGeo}
        rotation={[-Math.PI / 2, 0, 0]}
        position={[0, 0, 0]}
        receiveShadow
      >
        <meshStandardMaterial map={grassTex} color="#d6f0b2" roughness={0.95} />
      </mesh>
    </group>
  );
}

/* ── Soft grass variation patches + clover ─────────────────────────── */
export function GrassField() {
  const patches = useMemo(() => {
    const out: { x: number; z: number; s: number; c: string }[] = [];
    for (let i = 0; i < 26; i++) {
      const h = hash01("gp" + i);
      const h2 = hash01("gp2" + i);
      out.push({
        x: (h - 0.5) * (WORLD_W + 4),
        z: (h2 - 0.5) * (WORLD_D + 4),
        s: 1.4 + hash01("gs" + i) * 2.6,
        c: h > 0.5 ? AC.grassLight : AC.grassDark,
      });
    }
    return out;
  }, []);

  return (
    <group>
      {patches.map((p, i) => (
        <mesh
          key={i}
          rotation={[-Math.PI / 2, 0, 0]}
          position={[p.x, 0.006 + (i % 3) * 0.002, p.z]}
          receiveShadow
        >
          <circleGeometry args={[p.s, 20]} />
          <meshStandardMaterial
            color={p.c}
            roughness={1}
            transparent
            opacity={0.22}
            depthWrite={false}
          />
        </mesh>
      ))}
    </group>
  );
}

/* ── Pine tree — layered rounded cones ─────────────────────────────── */
export function ACTree({
  position,
  scale = 1,
  seed = "t",
}: {
  position: [number, number, number];
  scale?: number;
  seed?: string;
}) {
  const s = 0.9 + hash01(seed) * 0.4;
  const lean = (hash01(seed + "l") - 0.5) * 0.05;
  const h = scale * s;
  return (
    <group
      position={position}
      scale={h}
      rotation={[0, hash01(seed + "r") * Math.PI * 2, lean]}
    >
      <mesh position={[0, 0.28, 0]} castShadow>
        <cylinderGeometry args={[0.07, 0.12, 0.55, 7]} />
        {mat(AC.trunk)}
      </mesh>
      <mesh position={[0, 0.62, 0]} castShadow>
        <coneGeometry args={[0.55, 0.6, 9]} />
        {mat(AC.canopyDeep)}
      </mesh>
      <mesh position={[0, 1.0, 0]} castShadow>
        <coneGeometry args={[0.43, 0.58, 9]} />
        {mat(AC.canopyMid)}
      </mesh>
      <mesh position={[0, 1.35, 0]} castShadow>
        <coneGeometry args={[0.3, 0.52, 9]} />
        {mat(AC.canopyLite)}
      </mesh>
      <mesh position={[0, 1.64, 0]} castShadow>
        <coneGeometry args={[0.15, 0.36, 8]} />
        {mat(AC.canopyTip)}
      </mesh>
    </group>
  );
}

/* ── Round deciduous tree ──────────────────────────────────────────── */
export function ACRoundTree({
  position,
  scale = 1,
  seed = "r",
}: {
  position: [number, number, number];
  scale?: number;
  seed?: string;
}) {
  const s = scale * (0.9 + hash01(seed) * 0.25);
  return (
    <group position={position} scale={s}>
      <mesh position={[0, 0.4, 0]} castShadow>
        <cylinderGeometry args={[0.08, 0.11, 0.8, 7]} />
        {mat(AC.trunk)}
      </mesh>
      <mesh position={[0, 1.12, 0]} castShadow>
        <sphereGeometry args={[0.56, 12, 10]} />
        {mat(AC.canopyMid)}
      </mesh>
      <mesh position={[0.26, 1.3, 0.14]} castShadow>
        <sphereGeometry args={[0.34, 10, 8]} />
        {mat(AC.canopyLite)}
      </mesh>
      <mesh position={[-0.22, 1.22, -0.16]} castShadow>
        <sphereGeometry args={[0.3, 10, 8]} />
        {mat(AC.canopyDeep)}
      </mesh>
    </group>
  );
}

/* ── Rock ──────────────────────────────────────────────────────────── */
export function Rock({
  position,
  seed = "k",
  scale = 1,
}: {
  position: [number, number, number];
  seed?: string;
  scale?: number;
}) {
  const s = scale * (0.16 + hash01(seed) * 0.22);
  return (
    <mesh
      position={[position[0], s * 0.55, position[2]]}
      rotation={[
        hash01(seed + "rx") * Math.PI,
        hash01(seed + "ry") * Math.PI,
        0,
      ]}
      scale={[s * 1.35, s, s]}
      castShadow
      receiveShadow
    >
      <dodecahedronGeometry args={[1, 0]} />
      {mat(AC.stone, { roughness: 0.95 })}
    </mesh>
  );
}

/* ── Bush ──────────────────────────────────────────────────────────── */
export function Bush({
  position,
  seed = "b",
}: {
  position: [number, number, number];
  seed?: string;
}) {
  const s = 0.28 + hash01(seed) * 0.2;
  return (
    <group position={position} scale={s}>
      <mesh position={[0, 0.5, 0]} castShadow>
        <sphereGeometry args={[0.8, 10, 8]} />
        {mat(AC.canopyMid)}
      </mesh>
      <mesh position={[0.5, 0.35, 0.15]} castShadow>
        <sphereGeometry args={[0.55, 9, 7]} />
        {mat(AC.canopyLite)}
      </mesh>
      <mesh position={[-0.45, 0.35, -0.1]} castShadow>
        <sphereGeometry args={[0.5, 9, 7]} />
        {mat(AC.canopyDeep)}
      </mesh>
    </group>
  );
}

/* ── Flower tuft — petal ring + center ─────────────────────────────── */
export function ACFlowers({
  position,
  seed = "f",
}: {
  position: [number, number, number];
  seed?: string;
}) {
  const colors = [AC.flowerY, AC.flowerP, AC.flowerB, AC.flowerR];
  const c = colors[Math.floor(hash01(seed) * colors.length)];
  const petals = 5;
  return (
    <group position={position} rotation={[0, hash01(seed + "r") * Math.PI, 0]}>
      <mesh position={[0, 0.08, 0]}>
        <cylinderGeometry args={[0.012, 0.018, 0.16, 5]} />
        {mat(AC.canopyMid)}
      </mesh>
      {Array.from({ length: petals }, (_, i) => {
        const a = (i / petals) * Math.PI * 2;
        return (
          <mesh
            key={i}
            position={[Math.cos(a) * 0.05, 0.17, Math.sin(a) * 0.05]}
          >
            <sphereGeometry args={[0.035, 7, 6]} />
            {mat(c)}
          </mesh>
        );
      })}
      <mesh position={[0, 0.18, 0]}>
        <sphereGeometry args={[0.028, 7, 6]} />
        <meshStandardMaterial
          color="#f8e070"
          emissive="#f8e070"
          emissiveIntensity={0.25}
          roughness={0.6}
        />
      </mesh>
    </group>
  );
}

/* ── Chimney smoke — looping soft puffs ────────────────────────────── */
function smokeTexture(): THREE.Texture {
  const size = 64;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d")!;
  const g = ctx.createRadialGradient(32, 32, 2, 32, 32, 30);
  g.addColorStop(0, "rgba(255,255,255,0.85)");
  g.addColorStop(0.7, "rgba(255,255,255,0.32)");
  g.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}
let SMOKE_TEX: THREE.Texture | null = null;

export function ChimneySmoke({
  position,
  seed = "s",
}: {
  position: [number, number, number];
  seed?: string;
}) {
  const tex = useMemo(() => {
    if (!SMOKE_TEX) SMOKE_TEX = smokeTexture();
    return SMOKE_TEX;
  }, []);
  const group = useRef<THREE.Group>(null);
  const offset = useMemo(() => hash01(seed) * 4, [seed]);
  const N = 4;

  useFrame((state) => {
    if (!group.current) return;
    const t = state.clock.elapsedTime + offset;
    group.current.children.forEach((c, i) => {
      const phase = ((t * 0.28 + i / N) % 1 + 1) % 1;
      const sp = c as THREE.Sprite;
      sp.position.y = phase * 1.5;
      sp.position.x = Math.sin((phase * 3 + i) * 2.1) * 0.12 * phase;
      const s = 0.16 + phase * 0.5;
      sp.scale.set(s, s, s);
      (sp.material as THREE.SpriteMaterial).opacity =
        phase < 0.12 ? phase * 4 : 0.55 * (1 - phase);
    });
  });

  return (
    <group ref={group} position={position}>
      {Array.from({ length: N }, (_, i) => (
        <sprite key={i}>
          <spriteMaterial map={tex} transparent depthWrite={false} />
        </sprite>
      ))}
    </group>
  );
}

/* ── Butterflies — wandering, wing-flapping ────────────────────────── */
export function Butterflies({ seed = "bf" }: { seed?: string }) {
  const group = useRef<THREE.Group>(null);
  const items = useMemo(
    () =>
      Array.from({ length: 5 }, (_, i) => ({
        hx: (hash01(seed + "x" + i) - 0.5) * (WORLD_W - 6),
        hz: (hash01(seed + "z" + i) - 0.5) * (WORLD_D - 4),
        r: 1.6 + hash01(seed + "r" + i) * 2.4,
        v: 0.35 + hash01(seed + "v" + i) * 0.4,
        ph: hash01(seed + "p" + i) * Math.PI * 2,
        c: [AC.flowerY, AC.flowerP, "#ffffff", AC.flowerB][i % 4],
      })),
    [seed]
  );

  useFrame((state) => {
    if (!group.current) return;
    const t = state.clock.elapsedTime;
    group.current.children.forEach((b, i) => {
      const it = items[i];
      const a = t * it.v + it.ph;
      b.position.set(
        it.hx + Math.cos(a) * it.r,
        0.7 + Math.sin(t * 1.7 + it.ph) * 0.25,
        it.hz + Math.sin(a * 1.35) * it.r * 0.7
      );
      b.rotation.y = -a - Math.PI / 2;
      const flap = Math.sin(t * 18 + it.ph) * 0.75;
      const wings = b.children as THREE.Object3D[];
      if (wings[0]) wings[0].rotation.z = flap;
      if (wings[1]) wings[1].rotation.z = -flap;
    });
  });

  return (
    <group ref={group}>
      {items.map((it, i) => (
        <group key={i}>
          <mesh position={[-0.055, 0, 0]}>
            <planeGeometry args={[0.11, 0.09]} />
            <meshBasicMaterial color={it.c} side={THREE.DoubleSide} />
          </mesh>
          <mesh position={[0.055, 0, 0]}>
            <planeGeometry args={[0.11, 0.09]} />
            <meshBasicMaterial color={it.c} side={THREE.DoubleSide} />
          </mesh>
        </group>
      ))}
    </group>
  );
}

/* ── Log cabin house (world landmark) ──────────────────────────────── */
export function ACHouse({
  position,
  rotation = 0,
  accent = "#5B9CFF",
  glow = true,
}: {
  position: [number, number, number];
  rotation?: number;
  accent?: string;
  glow?: boolean;
}) {
  return (
    <group position={position} rotation={[0, rotation, 0]}>
      {/* stone foundation */}
      <mesh position={[0, 0.08, 0]} receiveShadow castShadow>
        <boxGeometry args={[1.9, 0.16, 1.55]} />
        {mat("#8f887a")}
      </mesh>

      {/* log walls */}
      <mesh position={[0, 0.72, 0]} castShadow receiveShadow>
        <boxGeometry args={[1.7, 1.15, 1.35]} />
        {mat(AC.log)}
      </mesh>
      {[-0.2, 0.05, 0.3, 0.55].map((y, i) => (
        <mesh key={i} position={[0, 0.45 + y * 0.6, 0.68]}>
          <boxGeometry args={[1.72, 0.045, 0.02]} />
          {mat(AC.logDark)}
        </mesh>
      ))}

      {/* hipped roof with accent ridge */}
      <mesh position={[0, 1.52, 0]} rotation={[0, Math.PI / 4, 0]} castShadow>
        <coneGeometry args={[1.52, 1.0, 4]} />
        {mat(AC.roof)}
      </mesh>
      <mesh position={[0, 1.55, 0]} rotation={[0, Math.PI / 4, 0]}>
        <coneGeometry args={[1.58, 0.22, 4]} />
        {mat(AC.roofDark)}
      </mesh>
      <mesh position={[0, 2.06, 0]}>
        <boxGeometry args={[0.2, 0.1, 0.2]} />
        {mat(AC.roofDark)}
      </mesh>

      {/* chimney + smoke */}
      <mesh position={[0.5, 1.75, -0.22]} castShadow>
        <boxGeometry args={[0.24, 0.55, 0.24]} />
        {mat(AC.stone)}
      </mesh>
      <mesh position={[0.5, 2.05, -0.22]}>
        <boxGeometry args={[0.3, 0.09, 0.3]} />
        {mat("#8a8478")}
      </mesh>
      <ChimneySmoke position={[0.5, 2.15, -0.22]} seed={accent} />

      {/* door with accent frame */}
      <mesh position={[0, 0.5, 0.69]} castShadow>
        <boxGeometry args={[0.42, 0.68, 0.05]} />
        {mat(accent)}
      </mesh>
      <mesh position={[0, 0.48, 0.72]}>
        <boxGeometry args={[0.32, 0.58, 0.04]} />
        {mat(AC.door)}
      </mesh>
      <mesh position={[0.1, 0.48, 0.75]}>
        <sphereGeometry args={[0.03, 8, 8]} />
        {mat("#e8c050", { roughness: 0.4, metalness: 0.4 })}
      </mesh>

      {/* windows — warm glow */}
      {(
        [
          [-0.5, 0.82, 0.69],
          [0.5, 0.82, 0.69],
        ] as [number, number, number][]
      ).map((p, i) => (
        <group key={i} position={p}>
          <mesh>
            <boxGeometry args={[0.36, 0.32, 0.04]} />
            {mat(AC.windowFrame)}
          </mesh>
          <mesh position={[0, 0, 0.02]}>
            <boxGeometry args={[0.3, 0.26, 0.02]} />
            <meshStandardMaterial
              color={AC.windowGlow}
              emissive={AC.windowGlow}
              emissiveIntensity={glow ? 1.8 : 0.2}
              roughness={0.35}
            />
          </mesh>
          <mesh position={[0, 0, 0.035]}>
            <boxGeometry args={[0.03, 0.26, 0.01]} />
            {mat(AC.windowFrame)}
          </mesh>
          <mesh position={[0, 0, 0.035]}>
            <boxGeometry args={[0.3, 0.03, 0.01]} />
            {mat(AC.windowFrame)}
          </mesh>
          {/* window box flowers */}
          <mesh position={[0, -0.2, 0.05]} castShadow>
            <boxGeometry args={[0.34, 0.07, 0.09]} />
            {mat("#7a5a34")}
          </mesh>
        </group>
      ))}

      {/* mailbox */}
      <group position={[1.15, 0, 0.4]}>
        <mesh position={[0, 0.28, 0]}>
          <cylinderGeometry args={[0.035, 0.035, 0.55, 6]} />
          {mat("#888")}
        </mesh>
        <mesh position={[0.1, 0.6, 0]} castShadow>
          <boxGeometry args={[0.32, 0.2, 0.18]} />
          {mat(AC.mailbox)}
        </mesh>
      </group>

      {/* short picket fence, front-left */}
      <group position={[-0.95, 0, 0.62]}>
        {[0, 0.22, 0.44].map((x, i) => (
          <mesh key={i} position={[-x, 0.16, 0]} castShadow>
            <boxGeometry args={[0.06, 0.32, 0.04]} />
            {mat(AC.logLite)}
          </mesh>
        ))}
        <mesh position={[-0.22, 0.24, 0]}>
          <boxGeometry args={[0.56, 0.045, 0.03]} />
          {mat(AC.logLite)}
        </mesh>
      </group>

      {/* accent pad ring under house */}
      <mesh position={[0, 0.015, 0]} rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
        <circleGeometry args={[1.35, 30]} />
        <meshStandardMaterial color={accent} transparent opacity={0.16} roughness={1} />
      </mesh>
    </group>
  );
}

/* ── Small cottage / level marker ──────────────────────────────────── */
export function ACCottage({
  position,
  color = "#5B9CFF",
  built = false,
}: {
  position: [number, number, number];
  color?: string;
  built?: boolean;
}) {
  return (
    <group position={position}>
      {/* status pad */}
      <mesh position={[0, 0.025, 0]} rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
        <circleGeometry args={[0.6, 26]} />
        <meshStandardMaterial color={color} roughness={0.7} metalness={0.05} />
      </mesh>
      <mesh position={[0, 0.035, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[0.52, 0.6, 26]} />
        <meshStandardMaterial
          color="#f6e6b2"
          emissive={built ? "#f6e6b2" : "#000000"}
          emissiveIntensity={built ? 0.25 : 0}
          roughness={0.6}
        />
      </mesh>

      {/* hut */}
      <mesh position={[0, 0.3, 0]} castShadow>
        <boxGeometry args={[0.56, 0.42, 0.5]} />
        {mat(AC.logLite)}
      </mesh>
      {/* roof takes the status color — readable from the sky */}
      <mesh position={[0, 0.62, 0]} rotation={[0, Math.PI / 4, 0]} castShadow>
        <coneGeometry args={[0.5, 0.38, 4]} />
        {mat(color)}
      </mesh>
      <mesh position={[0, 0.24, 0.26]}>
        <boxGeometry args={[0.15, 0.24, 0.04]} />
        {mat(AC.door)}
      </mesh>
      {/* tiny window, lit when built */}
      <mesh position={[0.17, 0.32, 0.26]}>
        <boxGeometry args={[0.1, 0.1, 0.03]} />
        <meshStandardMaterial
          color={AC.windowGlow}
          emissive={AC.windowGlow}
          emissiveIntensity={built ? 1.6 : 0.12}
          roughness={0.4}
        />
      </mesh>
      {built && (
        <group position={[0.3, 0, 0]}>
          <mesh position={[0, 0.42, 0]}>
            <cylinderGeometry args={[0.014, 0.014, 0.72, 6]} />
            {mat("#e8e4da")}
          </mesh>
          <mesh position={[0.1, 0.68, 0]}>
            <boxGeometry args={[0.19, 0.12, 0.015]} />
            <meshStandardMaterial
              color="#fbbf24"
              emissive="#fbbf24"
              emissiveIntensity={0.5}
              roughness={0.5}
            />
          </mesh>
        </group>
      )}
    </group>
  );
}

/* ── Mystery / ungrouped marker ────────────────────────────────────── */
export function ACMystery({ position }: { position: [number, number, number] }) {
  const ref = useRef<THREE.Group>(null);
  useFrame((state) => {
    if (ref.current) {
      ref.current.position.y =
        Math.sin(state.clock.elapsedTime * 2) * 0.08 + 0.42;
      ref.current.rotation.y = state.clock.elapsedTime * 0.6;
    }
  });
  return (
    <group position={position}>
      <mesh position={[0, 0.025, 0]} rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
        <circleGeometry args={[0.52, 24]} />
        <meshStandardMaterial color="#f0c94a" transparent opacity={0.4} roughness={0.7} />
      </mesh>
      <group ref={ref}>
        <mesh castShadow>
          <boxGeometry args={[0.44, 0.44, 0.44]} />
          <meshStandardMaterial
            color="#f5c842"
            emissive="#f5c842"
            emissiveIntensity={0.35}
            roughness={0.5}
          />
        </mesh>
        {([0, Math.PI / 2, Math.PI, -Math.PI / 2] as number[]).map((a, i) => (
          <group key={i} rotation={[0, a, 0]}>
            <mesh position={[0, 0.03, 0.225]}>
              <sphereGeometry args={[0.07, 8, 8]} />
              {mat("#7a4a10")}
            </mesh>
            <mesh position={[0, -0.13, 0.225]}>
              <sphereGeometry args={[0.04, 8, 8]} />
              {mat("#7a4a10")}
            </mesh>
          </group>
        ))}
      </group>
    </group>
  );
}

/* ── Lamp post — warm glow along paths ─────────────────────────────── */
export function LampPost({ position }: { position: [number, number, number] }) {
  return (
    <group position={position}>
      <mesh position={[0, 0.5, 0]} castShadow>
        <cylinderGeometry args={[0.03, 0.045, 1.0, 7]} />
        {mat("#4a423a")}
      </mesh>
      <mesh position={[0, 1.05, 0]} castShadow>
        <boxGeometry args={[0.14, 0.18, 0.14]} />
        <meshStandardMaterial
          color={AC.windowGlow}
          emissive={AC.windowGlow}
          emissiveIntensity={2.2}
          roughness={0.3}
        />
      </mesh>
      <mesh position={[0, 1.16, 0]}>
        <coneGeometry args={[0.13, 0.1, 4]} />
        {mat("#4a423a")}
      </mesh>
    </group>
  );
}

/* ── Dirt path — smooth ribbon geometry (2 draw calls per path) ────── */
function ribbonGeometry(
  points: { x: number; z: number }[],
  width: number
): THREE.BufferGeometry {
  const n = points.length;
  const pos = new Float32Array(n * 2 * 3);
  const uv = new Float32Array(n * 2 * 2);
  const idx: number[] = [];
  for (let i = 0; i < n; i++) {
    const p = points[i];
    const prev = points[Math.max(0, i - 1)];
    const next = points[Math.min(n - 1, i + 1)];
    let dx = next.x - prev.x;
    let dz = next.z - prev.z;
    const len = Math.hypot(dx, dz) || 1;
    dx /= len;
    dz /= len;
    const nx = -dz;
    const nz = dx;
    const w = width / 2;
    pos.set([p.x + nx * w, 0, p.z + nz * w, p.x - nx * w, 0, p.z - nz * w], i * 6);
    uv.set([0, i / (n - 1), 1, i / (n - 1)], i * 4);
    if (i < n - 1) {
      const a = i * 2;
      // wound so face normals point +Y (visible from above)
      idx.push(a, a + 2, a + 1, a + 1, a + 2, a + 3);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  g.setAttribute("uv", new THREE.BufferAttribute(uv, 2));
  g.setIndex(idx);
  g.computeVertexNormals();
  return g;
}

export function DirtPath({
  points,
  width = 1.15,
}: {
  points: { x: number; z: number }[];
  width?: number;
}) {
  const geoMain = useMemo(() => ribbonGeometry(points, width), [points, width]);
  const geoEdge = useMemo(
    () => ribbonGeometry(points, width + 0.28),
    [points, width]
  );
  return (
    <group>
      <mesh geometry={geoEdge} position={[0, 0.014, 0]} receiveShadow>
        <meshStandardMaterial
          color={AC.dirtEdge}
          roughness={0.97}
          side={THREE.DoubleSide}
        />
      </mesh>
      <mesh geometry={geoMain} position={[0, 0.022, 0]} receiveShadow>
        <meshStandardMaterial
          color={AC.dirtPath}
          roughness={0.94}
          side={THREE.DoubleSide}
        />
      </mesh>
    </group>
  );
}

/* ── Forest belt + ground clutter around the island edge ───────────── */
export function ForestBelt({ seed }: { seed: string }) {
  const HW = WORLD_W / 2;
  const HD = WORLD_D / 2;

  const trees = useMemo(() => {
    const out: {
      x: number;
      z: number;
      s: number;
      kind: "pine" | "round";
      id: string;
    }[] = [];
    // North treeline (behind everything) — two staggered rows on the island
    for (let i = 0; i < 16; i++) {
      out.push({
        x: -HW - 1 + i * ((WORLD_W + 2) / 15) + (hash01(seed + "nx" + i) - 0.5) * 0.8,
        z: -HD - 2.4 + (hash01(seed + "nz" + i) - 0.5) * 0.9,
        s: 1.05 + hash01(seed + "ns" + i) * 0.4,
        kind: "pine",
        id: "N" + i,
      });
    }
    for (let i = 0; i < 12; i++) {
      out.push({
        x: -HW + 0.6 + i * ((WORLD_W - 1) / 11) + (hash01(seed + "mx" + i) - 0.5) * 1.1,
        z: -HD - 0.9 + (hash01(seed + "mz" + i) - 0.5) * 0.8,
        s: 0.85 + hash01(seed + "ms" + i) * 0.4,
        kind: hash01(seed + "mk" + i) > 0.7 ? "round" : "pine",
        id: "M" + i,
      });
    }
    // West cluster
    for (let i = 0; i < 10; i++) {
      const row = Math.floor(i / 3);
      const col = i % 3;
      out.push({
        x: -HW - 2.2 + col * 0.95 + (hash01(seed + "wx" + i) - 0.5) * 0.6,
        z: -HD + 2.5 + row * 1.5 + (hash01(seed + "wz" + i) - 0.5) * 0.7,
        s: 0.9 + hash01(seed + "ws" + i) * 0.45,
        kind: "pine",
        id: "W" + i,
      });
    }
    // East cluster
    for (let i = 0; i < 9; i++) {
      const row = Math.floor(i / 3);
      const col = i % 3;
      out.push({
        x: HW + 0.6 + col * 0.95 + (hash01(seed + "ex" + i) - 0.5) * 0.6,
        z: -HD + 3 + row * 1.6 + (hash01(seed + "ez" + i) - 0.5) * 0.7,
        s: 0.85 + hash01(seed + "es" + i) * 0.4,
        kind: hash01(seed + "ek" + i) > 0.6 ? "round" : "pine",
        id: "E" + i,
      });
    }
    // South scattered accents (sparse, don't block camera)
    for (let i = 0; i < 6; i++) {
      out.push({
        x: -HW + 1 + i * ((WORLD_W - 2) / 5) + (hash01(seed + "sx" + i) - 0.5) * 1.4,
        z: HD + 1.6 + (hash01(seed + "sz" + i) - 0.5) * 0.8,
        s: 0.6 + hash01(seed + "ss" + i) * 0.3,
        kind: hash01(seed + "sk" + i) > 0.5 ? "round" : "pine",
        id: "S" + i,
      });
    }
    return out;
  }, [seed, HW, HD]);

  const flowers = useMemo(() => {
    const out: { x: number; z: number; id: string }[] = [];
    for (let i = 0; i < 30; i++) {
      out.push({
        x: (hash01(seed + "fx" + i) - 0.5) * (WORLD_W - 2),
        z: (hash01(seed + "fz" + i) - 0.5) * (WORLD_D - 1),
        id: "f" + i,
      });
    }
    return out;
  }, [seed]);

  const rocks = useMemo(() => {
    const out: { x: number; z: number; id: string }[] = [];
    for (let i = 0; i < 9; i++) {
      out.push({
        x: (hash01(seed + "rx" + i) - 0.5) * (WORLD_W + 3),
        z: (hash01(seed + "rz" + i) - 0.5) * (WORLD_D + 3),
        id: "r" + i,
      });
    }
    return out;
  }, [seed]);

  const bushes = useMemo(() => {
    const out: { x: number; z: number; id: string }[] = [];
    for (let i = 0; i < 12; i++) {
      out.push({
        x: (hash01(seed + "bx" + i) - 0.5) * (WORLD_W + 4),
        z: (hash01(seed + "bz" + i) - 0.5) * (WORLD_D + 4),
        id: "b" + i,
      });
    }
    return out;
  }, [seed]);

  return (
    <group>
      {trees.map((t) =>
        t.kind === "pine" ? (
          <ACTree key={t.id} position={[t.x, 0, t.z]} scale={t.s} seed={t.id} />
        ) : (
          <ACRoundTree key={t.id} position={[t.x, 0, t.z]} scale={t.s} seed={t.id} />
        )
      )}
      {flowers.map((f) => (
        <ACFlowers key={f.id} position={[f.x, 0, f.z]} seed={f.id} />
      ))}
      {rocks.map((r) => (
        <Rock key={r.id} position={[r.x, 0, r.z]} seed={r.id} />
      ))}
      {bushes.map((b) => (
        <Bush key={b.id} position={[b.x, 0, b.z]} seed={b.id} />
      ))}
    </group>
  );
}
