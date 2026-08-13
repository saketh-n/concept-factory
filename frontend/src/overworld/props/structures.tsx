import { useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import { AC, mat } from "./shared";
import { ChimneySmoke } from "./effects";

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
