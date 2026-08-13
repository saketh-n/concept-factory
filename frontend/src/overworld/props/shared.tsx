import * as THREE from "three";
import { WORLD_W, WORLD_D } from "../layout";

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
  canopyDeep: "#3f9a44",
  canopyMid: "#58bb50",
  canopyLite: "#7cd45e",
  canopyTip: "#9ce873",
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
export function mat(color: string, opts?: { roughness?: number; metalness?: number }) {
  return (
    <meshStandardMaterial
      color={color}
      roughness={opts?.roughness ?? 0.88}
      metalness={opts?.metalness ?? 0.02}
    />
  );
}

/* ── Shared geometry helpers ───────────────────────────────────────── */
export function roundedRectShape(w: number, h: number, r: number) {
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
export const ISL_W = WORLD_W + ISLAND_MARGIN * 2;
export const ISL_D = WORLD_D + ISLAND_MARGIN * 2;
export const ISL_R = 7;
export const SEA_Y = -1.42;


export type Exclusion = { x: number; z: number; r: number };

export function isExcluded(x: number, z: number, exclusions: Exclusion[]): boolean {
  for (let i = 0; i < exclusions.length; i++) {
    const e = exclusions[i];
    const dx = x - e.x;
    const dz = z - e.z;
    if (dx * dx + dz * dz < e.r * e.r) return true;
  }
  return false;
}

/* ── Instanced wind-swept grass blades — BOTW field centerpiece ────── */
