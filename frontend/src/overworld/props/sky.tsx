import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import { hash01 } from "../layout";

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

/* ── Sun glow — additive sprite hung high in the sky ────────────────── */
function sunGlowTexture(): THREE.Texture {
  const size = 256;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d")!;
  const g = ctx.createRadialGradient(
    size / 2,
    size / 2,
    0,
    size / 2,
    size / 2,
    size / 2
  );
  g.addColorStop(0, "rgba(255,255,255,1)");
  g.addColorStop(0.35, "rgba(255,250,235,0.55)");
  g.addColorStop(1, "rgba(255,245,220,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}
let SUN_GLOW_TEX: THREE.Texture | null = null;

export function SunGlow() {
  const tex = useMemo(() => {
    if (!SUN_GLOW_TEX) SUN_GLOW_TEX = sunGlowTexture();
    return SUN_GLOW_TEX;
  }, []);
  return (
    <sprite position={[30, 34, -46]} scale={[26, 26, 1]}>
      <spriteMaterial
        map={tex}
        transparent
        opacity={0.85}
        depthWrite={false}
        fog={false}
        blending={THREE.AdditiveBlending}
      />
    </sprite>
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
