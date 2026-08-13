import { useMemo } from "react";
import { hash01, WORLD_W, WORLD_D } from "../layout";
import { AC, isExcluded, mat, type Exclusion } from "./shared";

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
      {/* canopy spheres sized up ~15% for a fuller BOTW silhouette */}
      <mesh position={[0, 1.12, 0]} castShadow>
        <sphereGeometry args={[0.644, 12, 10]} />
        {mat(AC.canopyMid)}
      </mesh>
      <mesh position={[0.26, 1.3, 0.14]} castShadow>
        <sphereGeometry args={[0.391, 10, 8]} />
        {mat(AC.canopyLite)}
      </mesh>
      <mesh position={[-0.22, 1.22, -0.16]} castShadow>
        <sphereGeometry args={[0.345, 10, 8]} />
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

/* ── Boulders — big stylized rock clusters near island edges/corners ─ */
export function Boulders({
  exclusions,
  seed,
}: {
  exclusions: Exclusion[];
  seed: string;
}) {
  const clusters = useMemo(() => {
    const hw = WORLD_W / 2 + 1.2;
    const hd = WORLD_D / 2 + 1.2;
    const anchors: { x: number; z: number }[] = [
      { x: -hw, z: -hd },
      { x: hw, z: -hd },
      { x: -hw, z: hd },
      { x: hw, z: hd },
      { x: 0, z: -hd },
      { x: 0, z: hd },
    ];
    return anchors.map((a, ci) => {
      let x = a.x + (hash01(seed + "bx" + ci) - 0.5) * 3;
      let z = a.z + (hash01(seed + "bz" + ci) - 0.5) * 3;
      let tries = 0;
      while (isExcluded(x, z, exclusions) && tries < 8) {
        x += (hash01(seed + "bnx" + ci + "_" + tries) - 0.5) * 2;
        z += (hash01(seed + "bnz" + ci + "_" + tries) - 0.5) * 2;
        tries++;
      }
      const rockCount = 2 + Math.floor(hash01(seed + "brc" + ci) * 2); // 2..3
      const rocks = Array.from({ length: rockCount }, (_, ri) => {
        const rSeed = seed + ci + "br" + ri;
        const radius = 0.7 + hash01(rSeed + "rad") * 1.3;
        return {
          ox: (hash01("ox" + rSeed) - 0.5) * radius * 1.1,
          oz: (hash01("oz" + rSeed) - 0.5) * radius * 1.1,
          radius,
          rx: hash01(rSeed + "rx") * Math.PI,
          ry: hash01(rSeed + "ry") * Math.PI,
          rz: hash01(rSeed + "rz") * Math.PI,
          top: ri === rockCount - 1,
        };
      });
      const mossR =
        1.05 + hash01(seed + "moss" + ci) * 0.5;
      return { x, z, id: "bo" + ci, rocks, mossR };
    });
  }, [exclusions, seed]);

  return (
    <group>
      {clusters.map((c) => (
        <group key={c.id} position={[c.x, 0, c.z]}>
          <mesh
            rotation={[-Math.PI / 2, 0, 0]}
            position={[0, 0.008, 0]}
            receiveShadow
          >
            <circleGeometry args={[c.mossR, 20]} />
            <meshStandardMaterial
              color="#5c9a45"
              roughness={1}
              transparent
              opacity={0.5}
              depthWrite={false}
            />
          </mesh>
          {c.rocks.map((r, ri) => (
            <mesh
              key={ri}
              position={[r.ox, r.radius * 0.65, r.oz]}
              rotation={[r.rx, r.ry, r.rz]}
              scale={[r.radius, r.radius * 0.72, r.radius]}
              castShadow
              receiveShadow
            >
              <dodecahedronGeometry args={[1, 0]} />
              {mat(r.top ? "#c2cbc6" : "#97a3a6", { roughness: 0.9 })}
            </mesh>
          ))}
        </group>
      ))}
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
