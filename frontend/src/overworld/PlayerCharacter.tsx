import * as React from "react";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { useGLTF, useAnimations } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";

const MODEL_URL = "/models/rogue_hooded.glb";
const TARGET_HEIGHT = 1.45;

// KayKit prop/weapon meshes that ship attached to hand/back sockets and must
// stay hidden for an unarmed rogue. Matched case-insensitively as substrings.
const HIDDEN_MESH_PATTERN =
  /knife|dagger|crossbow|arrow|shield|weapon|throwable|sword|axe|spear|staff|1h|2h/i;

useGLTF.preload(MODEL_URL);

export default function RogueCharacter({
  movingRef,
  speed = 4.2,
}: {
  /** Parent flips this each frame; true while the player is walking. */
  movingRef: React.MutableRefObject<boolean>;
  /** Ground speed in world units/sec — used to match run cadence (avoid foot sliding). */
  speed?: number;
}) {
  const { scene, animations } = useGLTF(MODEL_URL) as unknown as {
    scene: THREE.Group;
    animations: THREE.AnimationClip[];
  };
  const { actions } = useAnimations(animations, scene);
  const currentClipRef = useRef<string>("Idle");

  // One-time cleanup: shadows on, weapon/prop meshes hidden.
  useEffect(() => {
    scene.traverse((obj) => {
      if (obj instanceof THREE.Mesh || obj instanceof THREE.SkinnedMesh) {
        obj.castShadow = true;
        obj.receiveShadow = false;
        if (HIDDEN_MESH_PATTERN.test(obj.name)) {
          obj.visible = false;
        }
      }
    });
  }, [scene]);

  // Normalize the rig to a fixed world height with feet resting on y=0.
  // Computed after hiding props so a stray weapon mesh can't skew the box.
  const { scale, yOffset } = useMemo(() => {
    const box = new THREE.Box3().setFromObject(scene);
    const rawHeight = box.max.y - box.min.y;
    const s = rawHeight > 0 ? TARGET_HEIGHT / rawHeight : 1;
    return { scale: s, yOffset: -box.min.y * s };
  }, [scene]);

  useEffect(() => {
    actions["Idle"]?.reset().fadeIn(0.22).play();
    currentClipRef.current = "Idle";
  }, [actions]);

  useFrame(() => {
    const targetClip = movingRef.current ? "Running_A" : "Idle";
    const current = currentClipRef.current;

    if (targetClip !== current) {
      actions[current]?.fadeOut(0.22);
      const next = actions[targetClip];
      next?.reset().fadeIn(0.22).play();
      currentClipRef.current = targetClip;
    }

    const active = actions[currentClipRef.current];
    if (active) {
      active.timeScale =
        currentClipRef.current === "Running_A"
          ? THREE.MathUtils.clamp(speed / 4.2, 0.75, 1.6)
          : 1;
    }
  });

  return (
    // base facing: +Z confirmed — cape geometry sits entirely at negative
    // local Z (hangs off the back), so the model already faces +Z, matching
    // the parent's atan2(dx, dz) facing convention. No flip needed here.
    <group scale={scale} position={[0, yOffset, 0]}>
      <primitive object={scene} />
    </group>
  );
}
