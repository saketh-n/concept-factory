import * as React from "react";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { useGLTF, useAnimations } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import {
  recolorRogueImageData,
  ROGUE_FALLBACK_HEX,
} from "./rogueMaterials";

const MODEL_URL = "/models/rogue_hooded.glb";
const TARGET_HEIGHT = 1.45;

// KayKit prop/weapon meshes that ship attached to hand/back sockets and must
// stay hidden for an unarmed rogue. Matched case-insensitively as substrings.
const HIDDEN_MESH_PATTERN =
  /knife|dagger|crossbow|arrow|shield|weapon|throwable|sword|axe|spear|staff|1h|2h/i;

/**
 * Target look: dark hooded rogue from player-ref.webp —
 * muted charcoal / gray-brown cloak silhouette, matte cloth, no bright accents.
 * The KayKit atlas is neon-green by default; we recolor it toward the ref.
 */
// Soft neutral multiply — texture carries the dark gray-brown; avoid pure black.
const ROGUE_TINT = new THREE.Color("#9a9894");
const ROGUE_ROUGHNESS = 0.9;
const ROGUE_METALNESS = 0.04;

useGLTF.preload(MODEL_URL);

/**
 * Remap a KayKit-style bright cloak texture toward a dark muted rogue palette.
 * Keeps luminance structure (folds, straps) while crushing green/orange cartoon hues.
 */
function recolorRogueTexture(source: THREE.Texture): THREE.CanvasTexture {
  const img = source.image as
    | HTMLImageElement
    | HTMLCanvasElement
    | ImageBitmap
    | undefined;
  if (!img || !("width" in img) || !img.width) {
    const c = document.createElement("canvas");
    c.width = c.height = 4;
    const ctx = c.getContext("2d")!;
    ctx.fillStyle = ROGUE_FALLBACK_HEX;
    ctx.fillRect(0, 0, 4, 4);
    const tex = new THREE.CanvasTexture(c);
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.flipY = source.flipY;
    return tex;
  }

  const w = img.width as number;
  const h = img.height as number;
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d")!;
  ctx.drawImage(img as CanvasImageSource, 0, 0);
  const imageData = ctx.getImageData(0, 0, w, h);
  recolorRogueImageData(imageData);
  ctx.putImageData(imageData, 0, 0);
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.flipY = source.flipY;
  tex.wrapS = source.wrapS;
  tex.wrapT = source.wrapT;
  tex.magFilter = source.magFilter;
  tex.minFilter = source.minFilter;
  tex.needsUpdate = true;
  return tex;
}

function retuneRogueMaterials(scene: THREE.Group): () => void {
  const disposables: THREE.Texture[] = [];
  const seen = new WeakSet<THREE.Material>();

  scene.traverse((obj) => {
    if (!(obj instanceof THREE.Mesh || obj instanceof THREE.SkinnedMesh)) return;
    obj.castShadow = true;
    obj.receiveShadow = false;

    if (HIDDEN_MESH_PATTERN.test(obj.name)) {
      obj.visible = false;
      return;
    }

    const mats = Array.isArray(obj.material) ? obj.material : [obj.material];
    for (const mat of mats) {
      if (!mat || seen.has(mat)) continue;
      seen.add(mat);

      if (
        mat instanceof THREE.MeshStandardMaterial ||
        mat instanceof THREE.MeshPhysicalMaterial
      ) {
        const std = mat as THREE.MeshStandardMaterial;
        if (std.map) {
          const recolored = recolorRogueTexture(std.map);
          disposables.push(recolored);
          std.map = recolored;
          std.map.needsUpdate = true;
        }
        // Multiply any residual color toward muted charcoal
        std.color.copy(ROGUE_TINT);
        std.roughness = ROGUE_ROUGHNESS;
        std.metalness = ROGUE_METALNESS;
        std.emissive?.setHex(0x000000);
        std.emissiveIntensity = 0;
        std.envMapIntensity = 0.35;
        std.needsUpdate = true;
      } else if (mat instanceof THREE.MeshBasicMaterial) {
        mat.color.copy(ROGUE_TINT);
        mat.needsUpdate = true;
      }
    }
  });

  return () => {
    for (const t of disposables) t.dispose();
  };
}

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

  // One-time cleanup: shadows on, weapon/prop meshes hidden, materials retuned.
  useEffect(() => {
    // Clone materials so we don't permanently mutate the cached GLTF.
    scene.traverse((obj) => {
      if (!(obj instanceof THREE.Mesh || obj instanceof THREE.SkinnedMesh)) return;
      if (Array.isArray(obj.material)) {
        obj.material = obj.material.map((m) => m.clone());
      } else if (obj.material) {
        obj.material = obj.material.clone();
      }
    });
    return retuneRogueMaterials(scene);
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
