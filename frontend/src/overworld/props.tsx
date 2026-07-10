import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import { hash01 } from "./layout";

/* ── Animal Crossing palette ───────────────────────────────────────── */
export const AC = {
  grass: "#8FBF6A",
  grassDark: "#6FA04E",
  grassLight: "#A8D47C",
  dirt: "#C9A882",
  dirtPath: "#C4A06A",
  dirtEdge: "#A8844E",
  dirtLight: "#D8BC8A",
  canopyDeep: "#2F8F3A",
  canopyMid: "#45B04A",
  canopyLite: "#6AD05A",
  canopyTip: "#8AE06A",
  trunk: "#6B4423",
  trunkDark: "#4A2E16",
  log: "#C9A882",
  logDark: "#A8885E",
  logLite: "#E0C8A0",
  roof: "#3D7A5C",
  roofDark: "#2A5A42",
  roofLite: "#4F9A72",
  windowGlow: "#FFE6A8",
  windowFrame: "#8B6914",
  door: "#7A4A28",
  doorDark: "#5A3218",
  mailbox: "#E07040",
  sky: "#B8DCF0",
  fog: "#C5E0B0",
  playerBody: "#3D5FBF",
  playerDark: "#2A4490",
  playerFeet: "#E05050",
  playerFace: "#F5C8A0",
  flowerY: "#F5E050",
  flowerP: "#F090B8",
  flowerB: "#90B8F0",
  stone: "#B0A898",
} as const;

/** Soft matte material helper — AC surfaces are matte, slightly toon. */
function mat(color: string, opts?: { roughness?: number; metalness?: number }) {
  return (
    <meshStandardMaterial
      color={color}
      roughness={opts?.roughness ?? 0.88}
      metalness={opts?.metalness ?? 0.02}
    />
  );
}

/* ── Pine tree (stacked soft cones — dense forest look) ─────────────── */
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
  const lean = (hash01(seed + "l") - 0.5) * 0.06;
  const h = scale * s;
  // AC pines: rounded cone layers with bright sun-facing tops
  return (
    <group position={position} scale={h} rotation={[0, hash01(seed + "r") * Math.PI * 2, lean]}>
      <mesh position={[0, 0.28, 0]} castShadow>
        <cylinderGeometry args={[0.07, 0.11, 0.55, 8]} />
        {mat(AC.trunk)}
      </mesh>
      {/* bottom skirt */}
      <mesh position={[0, 0.7, 0]} castShadow>
        <sphereGeometry args={[0.42, 10, 8, 0, Math.PI * 2, 0, Math.PI * 0.55]} />
        {mat(AC.canopyDeep)}
      </mesh>
      <mesh position={[0, 0.55, 0]} castShadow>
        <coneGeometry args={[0.52, 0.55, 10]} />
        {mat(AC.canopyDeep)}
      </mesh>
      <mesh position={[0, 0.95, 0]} castShadow>
        <coneGeometry args={[0.42, 0.55, 10]} />
        {mat(AC.canopyMid)}
      </mesh>
      <mesh position={[0, 1.3, 0]} castShadow>
        <coneGeometry args={[0.3, 0.5, 10]} />
        {mat(AC.canopyLite)}
      </mesh>
      <mesh position={[0, 1.55, 0]} castShadow>
        <coneGeometry args={[0.16, 0.38, 9]} />
        {mat(AC.canopyTip)}
      </mesh>
      {/* sun highlight blob on top-facing side */}
      <mesh position={[0.08, 1.35, 0.08]}>
        <sphereGeometry args={[0.12, 8, 6]} />
        <meshStandardMaterial
          color={AC.canopyTip}
          emissive={AC.canopyTip}
          emissiveIntensity={0.15}
          roughness={0.7}
          transparent
          opacity={0.7}
        />
      </mesh>
    </group>
  );
}

/* ── Round deciduous tree (softer, village edge) ───────────────────── */
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
        <cylinderGeometry args={[0.07, 0.1, 0.8, 8]} />
        {mat(AC.trunk)}
      </mesh>
      <mesh position={[0, 1.15, 0]} castShadow>
        <sphereGeometry args={[0.55, 12, 10]} />
        {mat(AC.canopyMid)}
      </mesh>
      <mesh position={[0.25, 1.3, 0.15]} castShadow>
        <sphereGeometry args={[0.35, 10, 8]} />
        {mat(AC.canopyLite)}
      </mesh>
      <mesh position={[-0.2, 1.25, -0.15]} castShadow>
        <sphereGeometry args={[0.32, 10, 8]} />
        {mat(AC.canopyDeep)}
      </mesh>
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
      {/* foundation / base trim */}
      <mesh position={[0, 0.08, 0]} receiveShadow castShadow>
        <boxGeometry args={[1.85, 0.16, 1.5]} />
        {mat("#3A5A8A")}
      </mesh>

      {/* log walls */}
      <mesh position={[0, 0.72, 0]} castShadow receiveShadow>
        <boxGeometry args={[1.7, 1.15, 1.35]} />
        {mat(AC.log)}
      </mesh>
      {/* log horizontal lines via thin darker strips */}
      {[-0.2, 0.05, 0.3, 0.55].map((y, i) => (
        <mesh key={i} position={[0, 0.45 + y * 0.6, 0.68]}>
          <boxGeometry args={[1.72, 0.045, 0.02]} />
          {mat(AC.logDark)}
        </mesh>
      ))}

      {/* roof — hip style, green like reference */}
      <mesh position={[0, 1.5, 0]} rotation={[0, Math.PI / 4, 0]} castShadow>
        <coneGeometry args={[1.5, 0.95, 4]} />
        {mat(AC.roof)}
      </mesh>
      <mesh position={[0, 1.9, 0]}>
        <boxGeometry args={[0.22, 0.09, 0.22]} />
        {mat(AC.roofDark)}
      </mesh>

      {/* chimney */}
      <mesh position={[0.5, 1.7, -0.22]} castShadow>
        <boxGeometry args={[0.24, 0.5, 0.24]} />
        {mat(AC.stone)}
      </mesh>
      <mesh position={[0.5, 1.98, -0.22]}>
        <boxGeometry args={[0.3, 0.09, 0.3]} />
        {mat("#909088")}
      </mesh>

      {/* door */}
      <mesh position={[0, 0.48, 0.69]} castShadow>
        <boxGeometry args={[0.36, 0.62, 0.06]} />
        {mat(AC.door)}
      </mesh>
      <mesh position={[0.12, 0.48, 0.73]}>
        <sphereGeometry args={[0.035, 8, 8]} />
        {mat("#E8C050")}
      </mesh>

      {/* windows — warm glow */}
      {(
        [
          [-0.5, 0.8, 0.69],
          [0.5, 0.8, 0.69],
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
              emissive={glow ? AC.windowGlow : "#886622"}
              emissiveIntensity={glow ? 1.1 : 0.15}
              roughness={0.35}
            />
          </mesh>
          <mesh position={[0, 0, 0.03]}>
            <boxGeometry args={[0.03, 0.26, 0.01]} />
            {mat(AC.windowFrame)}
          </mesh>
          <mesh position={[0, 0, 0.03]}>
            <boxGeometry args={[0.3, 0.03, 0.01]} />
            {mat(AC.windowFrame)}
          </mesh>
        </group>
      ))}

      {/* side window (pinkish like ref) */}
      <mesh position={[0.86, 0.6, 0.15]} rotation={[0, Math.PI / 2, 0]}>
        <boxGeometry args={[0.3, 0.24, 0.04]} />
        {mat("#E8A0B0")}
      </mesh>

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
        <mesh position={[0.1, 0.72, 0]}>
          <boxGeometry args={[0.34, 0.05, 0.2]} />
          {mat("#C05030")}
        </mesh>
      </group>

      {/* soft pad ring under house */}
      <mesh position={[0, 0.02, 0]} rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
        <circleGeometry args={[1.3, 28]} />
        <meshStandardMaterial color={accent} transparent opacity={0.22} roughness={1} />
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
      {/* stone pad */}
      <mesh position={[0, 0.03, 0]} rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
        <circleGeometry args={[0.55, 24]} />
        <meshStandardMaterial color={color} roughness={0.75} metalness={0.05} />
      </mesh>
      <mesh position={[0, 0.04, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[0.48, 0.55, 24]} />
        <meshStandardMaterial color="#F0D878" roughness={0.6} />
      </mesh>

      {/* tiny hut */}
      <mesh position={[0, 0.28, 0]} castShadow>
        <boxGeometry args={[0.55, 0.4, 0.5]} />
        {mat(AC.logLite)}
      </mesh>
      <mesh position={[0, 0.58, 0]} rotation={[0, Math.PI / 4, 0]} castShadow>
        <coneGeometry args={[0.48, 0.35, 4]} />
        {mat(built ? AC.roofLite : AC.roof)}
      </mesh>
      <mesh position={[0, 0.22, 0.26]}>
        <boxGeometry args={[0.14, 0.22, 0.04]} />
        {mat(AC.door)}
      </mesh>
      {built && (
        <mesh position={[0.28, 0.55, 0]}>
          {/* flag pole */}
          <cylinderGeometry args={[0.015, 0.015, 0.5, 6]} />
          {mat("#EEE")}
        </mesh>
      )}
      {built && (
        <mesh position={[0.38, 0.7, 0]}>
          <boxGeometry args={[0.18, 0.12, 0.02]} />
          {mat("#F0C94A")}
        </mesh>
      )}
    </group>
  );
}

/* ── Mystery / ungrouped marker ────────────────────────────────────── */
export function ACMystery({ position }: { position: [number, number, number] }) {
  const ref = useRef<THREE.Group>(null);
  useFrame((state) => {
    if (ref.current) {
      ref.current.position.y = Math.sin(state.clock.elapsedTime * 2) * 0.08 + 0.15;
      ref.current.rotation.y = state.clock.elapsedTime * 0.6;
    }
  });
  return (
    <group position={position}>
      <mesh position={[0, 0.03, 0]} rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
        <circleGeometry args={[0.5, 24]} />
        <meshStandardMaterial color="#F0C94A" roughness={0.7} />
      </mesh>
      <group ref={ref}>
        <mesh castShadow>
          <boxGeometry args={[0.45, 0.45, 0.45]} />
          {mat("#F0C94A")}
        </mesh>
        {/* ? approximated as two blobs */}
        <mesh position={[0, 0.05, 0.24]}>
          <sphereGeometry args={[0.08, 8, 8]} />
          {mat("#C06020")}
        </mesh>
        <mesh position={[0, -0.12, 0.24]}>
          <sphereGeometry args={[0.05, 8, 8]} />
          {mat("#C06020")}
        </mesh>
      </group>
    </group>
  );
}

/* ── Player (cute rounded villager-ish explorer) ───────────────────── */
export function ACPlayer({
  position,
  facing,
  walking,
}: {
  position: [number, number, number];
  facing: number; // yaw radians
  walking: boolean;
}) {
  const group = useRef<THREE.Group>(null);
  const bob = useRef(0);

  useFrame((_, dt) => {
    if (!group.current) return;
    bob.current += dt * (walking ? 12 : 3);
    const y = walking
      ? Math.abs(Math.sin(bob.current)) * 0.08
      : Math.sin(bob.current) * 0.02 + 0.02;
    group.current.position.y = y;
    // smooth face
    const cur = group.current.rotation.y;
    let diff = facing - cur;
    while (diff > Math.PI) diff -= Math.PI * 2;
    while (diff < -Math.PI) diff += Math.PI * 2;
    group.current.rotation.y = cur + diff * Math.min(1, dt * 12);
  });

  return (
    <group position={position}>
      {/* shadow disc */}
      <mesh position={[0, 0.02, 0]} rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
        <circleGeometry args={[0.28, 16]} />
        <meshStandardMaterial color="#000" transparent opacity={0.22} roughness={1} />
      </mesh>
      <group ref={group}>
        {/* feet */}
        <mesh position={[-0.08, 0.08, 0.06]} castShadow>
          <sphereGeometry args={[0.09, 10, 8]} />
          {mat(AC.playerFeet)}
        </mesh>
        <mesh position={[0.08, 0.08, 0.06]} castShadow>
          <sphereGeometry args={[0.09, 10, 8]} />
          {mat(AC.playerFeet)}
        </mesh>
        {/* body */}
        <mesh position={[0, 0.32, 0]} castShadow>
          <capsuleGeometry args={[0.18, 0.22, 6, 12]} />
          {mat(AC.playerBody)}
        </mesh>
        {/* head */}
        <mesh position={[0, 0.62, 0]} castShadow>
          <sphereGeometry args={[0.2, 14, 12]} />
          {mat(AC.playerBody)}
        </mesh>
        {/* face plate */}
        <mesh position={[0, 0.6, 0.14]}>
          <sphereGeometry args={[0.12, 10, 8]} />
          {mat(AC.playerFace)}
        </mesh>
        {/* eyes */}
        <mesh position={[-0.05, 0.62, 0.22]}>
          <sphereGeometry args={[0.03, 8, 8]} />
          {mat("#1A1A1A")}
        </mesh>
        <mesh position={[0.05, 0.62, 0.22]}>
          <sphereGeometry args={[0.03, 8, 8]} />
          {mat("#1A1A1A")}
        </mesh>
        {/* ears / hood bumps */}
        <mesh position={[-0.16, 0.72, 0]} castShadow>
          <sphereGeometry args={[0.08, 8, 8]} />
          {mat(AC.playerDark)}
        </mesh>
        <mesh position={[0.16, 0.72, 0]} castShadow>
          <sphereGeometry args={[0.08, 8, 8]} />
          {mat(AC.playerDark)}
        </mesh>
        {/* backpack */}
        <mesh position={[0, 0.35, -0.16]} castShadow>
          <boxGeometry args={[0.22, 0.22, 0.1]} />
          {mat("#5A3A20")}
        </mesh>
      </group>
    </group>
  );
}

/* ── Flower tuft ───────────────────────────────────────────────────── */
export function ACFlowers({
  position,
  seed = "f",
}: {
  position: [number, number, number];
  seed?: string;
}) {
  const colors = [AC.flowerY, AC.flowerP, AC.flowerB];
  const c = colors[Math.floor(hash01(seed) * colors.length)];
  return (
    <group position={position}>
      <mesh position={[0, 0.06, 0]}>
        <cylinderGeometry args={[0.01, 0.015, 0.12, 5]} />
        {mat(AC.canopyMid)}
      </mesh>
      <mesh position={[0, 0.14, 0]}>
        <sphereGeometry args={[0.05, 8, 6]} />
        {mat(c)}
      </mesh>
      <mesh position={[0.06, 0.05, 0.03]}>
        <sphereGeometry args={[0.035, 6, 5]} />
        {mat(colors[(Math.floor(hash01(seed + "b") * 3) + 1) % 3])}
      </mesh>
    </group>
  );
}

/* ── Dirt path — overlapping discs for soft AC curves ──────────────── */
export function DirtPath({
  points,
  width = 1.15,
}: {
  points: { x: number; z: number }[];
  width?: number;
}) {
  // densify samples for smooth curves
  const stamps = useMemo(() => {
    if (points.length < 2) return [] as { x: number; z: number }[];
    const out: { x: number; z: number }[] = [];
    for (let i = 0; i < points.length - 1; i++) {
      const a = points[i];
      const b = points[i + 1];
      const dist = Math.hypot(b.x - a.x, b.z - a.z);
      const steps = Math.max(2, Math.ceil(dist / 0.22));
      for (let s = 0; s < steps; s++) {
        const t = s / steps;
        out.push({ x: a.x + (b.x - a.x) * t, z: a.z + (b.z - a.z) * t });
      }
    }
    out.push(points[points.length - 1]);
    return out;
  }, [points]);

  const r = width * 0.52;
  const rEdge = r + 0.14;

  return (
    <group>
      {stamps.map((p, i) => (
        <mesh
          key={`e${i}`}
          position={[p.x, 0.016, p.z]}
          rotation={[-Math.PI / 2, 0, 0]}
          receiveShadow
        >
          <circleGeometry args={[rEdge, 20]} />
          <meshStandardMaterial color={AC.dirtEdge} roughness={0.96} />
        </mesh>
      ))}
      {stamps.map((p, i) => (
        <mesh
          key={`d${i}`}
          position={[p.x, 0.022, p.z]}
          rotation={[-Math.PI / 2, 0, 0]}
          receiveShadow
        >
          <circleGeometry args={[r, 20]} />
          <meshStandardMaterial color={AC.dirtPath} roughness={0.93} />
        </mesh>
      ))}
      {/* soft center highlight */}
      {stamps
        .filter((_, i) => i % 2 === 0)
        .map((p, i) => (
          <mesh
            key={`h${i}`}
            position={[p.x, 0.026, p.z]}
            rotation={[-Math.PI / 2, 0, 0]}
          >
            <circleGeometry args={[r * 0.45, 12]} />
            <meshStandardMaterial
              color={AC.dirtLight}
              roughness={1}
              transparent
              opacity={0.35}
            />
          </mesh>
        ))}
    </group>
  );
}

/* ── Grass field — tiled soft texture like AC lawn ─────────────────── */
export function GrassField() {
  const texture = useMemo(() => {
    const size = 128;
    const canvas = document.createElement("canvas");
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext("2d")!;
    // base
    ctx.fillStyle = "#8FBF6A";
    ctx.fillRect(0, 0, size, size);
    // soft checker / tuft noise (AC lawn is faintly tiled)
    for (let y = 0; y < size; y++) {
      for (let x = 0; x < size; x++) {
        const n =
          Math.sin(x * 0.35) * Math.cos(y * 0.31) +
          Math.sin((x + y) * 0.18) * 0.5;
        const cell = ((Math.floor(x / 16) + Math.floor(y / 16)) % 2) * 0.04;
        const v = 0.55 + n * 0.06 + cell;
        const g = Math.floor(140 + v * 50);
        const r = Math.floor(90 + v * 30);
        const b = Math.floor(60 + v * 25);
        if ((x * 13 + y * 7) % 11 === 0) {
          ctx.fillStyle = `rgba(${r},${g},${b},0.55)`;
          ctx.fillRect(x, y, 1, 1);
        }
      }
    }
    // sparse flower dots
    for (let i = 0; i < 40; i++) {
      const x = (Math.sin(i * 12.1) * 0.5 + 0.5) * size;
      const y = (Math.cos(i * 9.7) * 0.5 + 0.5) * size;
      ctx.fillStyle = i % 3 === 0 ? "#f5e05088" : "#90c07066";
      ctx.beginPath();
      ctx.arc(x, y, 1.2, 0, Math.PI * 2);
      ctx.fill();
    }
    const tex = new THREE.CanvasTexture(canvas);
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
    tex.repeat.set(14, 10);
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.magFilter = THREE.LinearFilter;
    tex.minFilter = THREE.LinearMipmapLinearFilter;
    return tex;
  }, []);

  const patches = useMemo(() => {
    const out: { x: number; z: number; s: number; c: string }[] = [];
    for (let i = 0; i < 28; i++) {
      const h = hash01("gp" + i);
      const h2 = hash01("gp2" + i);
      out.push({
        x: (h - 0.5) * 28,
        z: (h2 - 0.5) * 20,
        s: 1.2 + hash01("gs" + i) * 2.4,
        c: h > 0.5 ? AC.grassLight : AC.grassDark,
      });
    }
    return out;
  }, []);

  return (
    <group>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, 0]} receiveShadow>
        <planeGeometry args={[42, 32, 1, 1]} />
        <meshStandardMaterial map={texture} roughness={0.95} color="#c8e8a8" />
      </mesh>
      {patches.map((p, i) => (
        <mesh
          key={i}
          rotation={[-Math.PI / 2, 0, 0]}
          position={[p.x, 0.004, p.z]}
          receiveShadow
        >
          <circleGeometry args={[p.s, 18]} />
          <meshStandardMaterial
            color={p.c}
            roughness={1}
            transparent
            opacity={0.28}
          />
        </mesh>
      ))}
    </group>
  );
}

/* ── Forest belt generator ─────────────────────────────────────────── */
export function ForestBelt({ seed }: { seed: string }) {
  const trees = useMemo(() => {
    const out: {
      x: number;
      z: number;
      s: number;
      kind: "pine" | "round";
      id: string;
    }[] = [];
    // Left forest
    for (let i = 0; i < 28; i++) {
      const row = Math.floor(i / 4);
      const col = i % 4;
      const jx = (hash01(seed + "lx" + i) - 0.5) * 0.7;
      const jz = (hash01(seed + "lz" + i) - 0.5) * 0.7;
      out.push({
        x: -12.5 + col * 0.85 + jx,
        z: -8 + row * 1.05 + jz,
        s: 0.9 + hash01(seed + "ls" + i) * 0.45,
        kind: "pine",
        id: "L" + i,
      });
    }
    // Right forest
    for (let i = 0; i < 18; i++) {
      const row = Math.floor(i / 3);
      const col = i % 3;
      out.push({
        x: 11 + col * 0.9 + (hash01(seed + "rx" + i) - 0.5) * 0.6,
        z: -6 + row * 1.1 + (hash01(seed + "rz" + i) - 0.5) * 0.6,
        s: 0.85 + hash01(seed + "rs" + i) * 0.4,
        kind: hash01(seed + "rk" + i) > 0.6 ? "round" : "pine",
        id: "R" + i,
      });
    }
    // Back row
    for (let i = 0; i < 14; i++) {
      out.push({
        x: -8 + i * 1.3 + (hash01(seed + "bx" + i) - 0.5) * 0.5,
        z: -9.5 + (hash01(seed + "bz" + i) - 0.5) * 0.8,
        s: 1.0 + hash01(seed + "bs" + i) * 0.35,
        kind: "pine",
        id: "B" + i,
      });
    }
    return out;
  }, [seed]);

  const flowers = useMemo(() => {
    const out: { x: number; z: number; id: string }[] = [];
    for (let i = 0; i < 24; i++) {
      out.push({
        x: (hash01(seed + "fx" + i) - 0.5) * 18,
        z: (hash01(seed + "fz" + i) - 0.5) * 14,
        id: "f" + i,
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
    </group>
  );
}
