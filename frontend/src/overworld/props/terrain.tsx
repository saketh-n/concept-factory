import { useEffect, useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import { hash01, WORLD_W, WORLD_D } from "../layout";
import {
  AC,
  ISL_D,
  ISL_R,
  ISL_W,
  SEA_Y,
  isExcluded,
  mat,
  roundedRectShape,
  type Exclusion,
} from "./shared";

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

/* ── Vista — hazy hills + mountains beyond the ocean horizon ───────── */
const VISTA_HILL_COUNT = 4;

export function Vista() {
  const hills = useMemo(() => {
    return Array.from({ length: VISTA_HILL_COUNT }, (_, i) => {
      const angle = (hash01("vha" + i) - 0.5) * Math.PI * 1.7;
      // Keep dist - radius comfortably beyond the island's ~23-unit half-diagonal
      // or the dome surface pokes up through the plateau and buries the grass.
      const radius = 8 + hash01("vhr" + i) * 5;
      const dist = radius + 30 + hash01("vhd" + i) * 10;
      const x = Math.sin(angle) * dist;
      const z = -Math.cos(angle) * dist;
      return { x, z, radius, id: i };
    });
  }, []);

  const mountainCount = 9 + Math.floor(hash01("vmc") * 3); // 9..11
  const mountains = useMemo(() => {
    return Array.from({ length: mountainCount }, (_, i) => {
      const angle = (hash01("vma" + i) - 0.5) * Math.PI * 1.8;
      const dist = 52 + hash01("vmd" + i) * 23;
      const x = Math.sin(angle) * dist;
      let z = -Math.cos(angle) * dist;
      if (z > 30) z = 30 - hash01("vm" + i + "zc") * 18;
      const radius = 7 + hash01("vmr" + i) * 8;
      const height = 7 + hash01("vmh" + i) * 7;
      return { x, z, radius, height, id: i };
    });
  }, [mountainCount]);

  const tallestIds = useMemo(() => {
    return new Set(
      [...mountains]
        .sort((a, b) => b.height - a.height)
        .slice(0, 4)
        .map((m) => m.id)
    );
  }, [mountains]);

  return (
    <group>
      {hills.map((h) => (
        <mesh
          key={h.id}
          position={[h.x, SEA_Y + h.radius * 0.28 * 0.35, h.z]}
          scale={[1, 0.28, 1]}
        >
          <sphereGeometry args={[h.radius, 16, 12]} />
          <meshStandardMaterial color="#6fb254" roughness={0.95} />
        </mesh>
      ))}
      {mountains.map((m) => (
        <group key={m.id} position={[m.x, 0, m.z]}>
          <mesh position={[0, m.height * 0.42, 0]}>
            <coneGeometry args={[m.radius, m.height, 7]} />
            <meshStandardMaterial color="#8aa8bd" roughness={1} flatShading />
          </mesh>
          {tallestIds.has(m.id) && (
            <mesh position={[0, m.height * 0.42 + m.height * 0.42, 0]}>
              <coneGeometry args={[m.radius * 0.32, m.height * 0.32, 7]} />
              <meshStandardMaterial color="#ffffff" roughness={0.9} flatShading />
            </mesh>
          )}
        </group>
      ))}
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
  // Brightened base — BOTW vibrant yellow-green rather than the older muted tone.
  ctx.fillStyle = "#85c161";
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
            opacity={0.12}
            depthWrite={false}
          />
        </mesh>
      ))}
    </group>
  );
}

/* ── Shared exclusion-circle helper (stops / paths / lamps punch-outs) ─ */

const GRASS_COUNT = 26000;
const GRASS_BLADE_WIDTH = 0.045;
const GRASS_BLADE_HEIGHT = 0.34;

/** Tapered blade: base pinned at y=0, narrows to a point at the tip. */
function bladeGeometry(width: number, height: number): THREE.BufferGeometry {
  const geo = new THREE.PlaneGeometry(width, height, 1, 3);
  geo.translate(0, height / 2, 0);
  const pos = geo.getAttribute("position") as THREE.BufferAttribute;
  const heightFrac = new Float32Array(pos.count);
  for (let i = 0; i < pos.count; i++) {
    const frac = THREE.MathUtils.clamp(pos.getY(i) / height, 0, 1);
    pos.setX(i, pos.getX(i) * (1 - frac));
    heightFrac[i] = frac;
  }
  pos.needsUpdate = true;
  geo.setAttribute("heightFrac", new THREE.BufferAttribute(heightFrac, 1));
  geo.computeVertexNormals();
  return geo;
}

function grassMaterial(): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    side: THREE.DoubleSide,
    fog: true,
    uniforms: {
      uTime: { value: 0 },
      fogColor: { value: new THREE.Color() },
      fogNear: { value: 1 },
      fogFar: { value: 1000 },
    },
    vertexShader: /* glsl */ `
      attribute float heightFrac;
      attribute float iRandom;
      uniform float uTime;
      varying float vHeightFrac;
      varying float vRandom;
      varying float vFacing;
      #include <fog_pars_vertex>
      void main() {
        vHeightFrac = heightFrac;
        vRandom = iRandom;

        vec4 worldPos = instanceMatrix * vec4(position, 1.0);
        float bend = heightFrac * heightFrac;
        float sway = sin(uTime * 1.6 + worldPos.x * 0.9 + worldPos.z * 0.7) * 0.18 * bend;
        worldPos.x += sway;
        worldPos.z += sway * 0.6;

        vec3 worldNormal = normalize(mat3(instanceMatrix) * vec3(0.0, 0.0, 1.0));
        vec3 viewDir = normalize(cameraPosition - worldPos.xyz);
        vFacing = dot(worldNormal, viewDir);

        vec4 mvPosition = modelViewMatrix * worldPos;
        gl_Position = projectionMatrix * mvPosition;
        #include <fog_vertex>
      }
    `,
    fragmentShader: /* glsl */ `
      varying float vHeightFrac;
      varying float vRandom;
      varying float vFacing;
      #include <fog_pars_fragment>
      void main() {
        // sRGB constants linearized so the colorspace conversion below is correct
        vec3 rootColor = pow(vec3(0.247, 0.478, 0.2), vec3(2.2));
        vec3 tipColor = pow(vec3(0.663, 0.851, 0.306), vec3(2.2));
        float t = pow(clamp(vHeightFrac, 0.0, 1.0), 0.75);
        vec3 color = mix(rootColor, tipColor, t);

        // ±7% per-instance hue/brightness jitter
        color *= 1.0 + (vRandom - 0.5) * 0.14;

        // subtle darkening for blades facing away from the camera
        float facingDark = smoothstep(-1.0, 0.2, vFacing);
        color *= mix(0.82, 1.0, facingDark);

        gl_FragColor = vec4(color, 1.0);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
        #include <fog_fragment>
      }
    `,
  });
}

export function GrassBlades({
  exclusions,
  seed,
}: {
  exclusions: Exclusion[];
  seed: string;
}) {
  const mesh = useMemo(() => {
    const geo = bladeGeometry(GRASS_BLADE_WIDTH, GRASS_BLADE_HEIGHT);
    const material = grassMaterial();
    const m = new THREE.InstancedMesh(geo, material, GRASS_COUNT);

    const hw = WORLD_W / 2 + 3.4;
    const hd = WORLD_D / 2 + 3.4;
    const rnd = new Float32Array(GRASS_COUNT);
    const mtx = new THREE.Matrix4();
    const q = new THREE.Quaternion();
    const s = new THREE.Vector3();
    const p = new THREE.Vector3();
    const axis = new THREE.Vector3(0, 1, 0);

    let placedCount = 0;
    let i = 0;
    const maxTries = GRASS_COUNT * 3;
    while (placedCount < GRASS_COUNT && i < maxTries) {
      const x = (hash01(seed + "gx" + i) - 0.5) * 2 * hw;
      const z = (hash01(seed + "gz" + i) - 0.5) * 2 * hd;
      i++;
      if (isExcluded(x, z, exclusions)) continue;
      const ry = hash01(seed + "gr" + i) * Math.PI * 2;
      const sc = 0.7 + hash01(seed + "gs" + i) * 0.8;
      p.set(x, 0, z);
      q.setFromAxisAngle(axis, ry);
      s.set(1, sc, 1);
      mtx.compose(p, q, s);
      m.setMatrixAt(placedCount, mtx);
      rnd[placedCount] = hash01(seed + "gh" + i);
      placedCount++;
    }
    m.count = placedCount;
    m.instanceMatrix.needsUpdate = true;
    geo.setAttribute(
      "iRandom",
      new THREE.InstancedBufferAttribute(rnd.slice(0, placedCount), 1)
    );
    m.frustumCulled = false;
    return m;
  }, [exclusions, seed]);

  useEffect(() => {
    return () => {
      mesh.geometry.dispose();
      (mesh.material as THREE.Material).dispose();
    };
  }, [mesh]);

  useFrame((state) => {
    (mesh.material as THREE.ShaderMaterial).uniforms.uTime.value =
      state.clock.elapsedTime;
  });

  return <primitive object={mesh} />;
}

/* ── Red plume grass — small clusters of thin crimson blades ───────── */
export function RedGrass({
  exclusions,
  seed,
}: {
  exclusions: Exclusion[];
  seed: string;
}) {
  const clusters = useMemo(() => {
    const hw = WORLD_W / 2 + 1;
    const hd = WORLD_D / 2 + 1;
    const out: {
      x: number;
      z: number;
      id: string;
      blades: { ox: number; oz: number; h: number; ry: number }[];
    }[] = [];
    for (let ci = 0; ci < 14; ci++) {
      let x = (hash01(seed + "rgx" + ci) - 0.5) * 2 * hw;
      let z = (hash01(seed + "rgz" + ci) - 0.5) * 2 * hd;
      let tries = 0;
      while (isExcluded(x, z, exclusions) && tries < 10) {
        x = (hash01(seed + "rgx2" + ci + "_" + tries) - 0.5) * 2 * hw;
        z = (hash01(seed + "rgz2" + ci + "_" + tries) - 0.5) * 2 * hd;
        tries++;
      }
      if (isExcluded(x, z, exclusions)) continue;
      const bladeCount = 3 + Math.floor(hash01(seed + "rgn" + ci) * 3); // 3..5
      const blades = Array.from({ length: bladeCount }, (_, bi) => {
        const bSeed = seed + ci + "b" + bi;
        return {
          ox: (hash01("ox" + bSeed) - 0.5) * 0.22,
          oz: (hash01("oz" + bSeed) - 0.5) * 0.22,
          h: 0.25 + hash01("h" + bSeed) * 0.2,
          ry: hash01("ry" + bSeed) * Math.PI * 2,
        };
      });
      out.push({ x, z, id: "rg" + ci, blades });
    }
    return out;
  }, [exclusions, seed]);

  return (
    <group>
      {clusters.map((c) => (
        <group key={c.id} position={[c.x, 0, c.z]}>
          {c.blades.map((b, bi) => (
            <mesh key={bi} position={[b.ox, b.h / 2, b.oz]} rotation={[0, b.ry, 0]}>
              <coneGeometry args={[0.04, b.h, 5]} />
              <meshStandardMaterial color="#c25848" roughness={0.85} />
            </mesh>
          ))}
        </group>
      ))}
    </group>
  );
}

/* ── Pine tree — layered rounded cones ─────────────────────────────── */

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
