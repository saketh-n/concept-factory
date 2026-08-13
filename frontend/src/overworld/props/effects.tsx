import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import { hash01, WORLD_W, WORLD_D } from "../layout";
import { AC } from "./shared";

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
