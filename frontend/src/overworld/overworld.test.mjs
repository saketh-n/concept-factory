/**
 * Structural + pure-function tests for the overworld map polish.
 * Runs with plain Node (no vitest) against shipped source via dynamic import
 * of pure modules and filesystem assertions on the real entry points.
 *
 * Usage: node src/overworld/overworld.test.mjs
 */
import { readFileSync, existsSync } from "fs";
import path from "path";
import { fileURLToPath, pathToFileURL } from "url";
import assert from "assert";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(__dirname, "../..");
const src = (p) => path.join(frontendRoot, "src", p);

let failed = 0;
async function check(name, fn) {
  try {
    await fn();
    console.log("  ok  ", name);
  } catch (e) {
    failed++;
    console.error("  FAIL", name);
    console.error("       ", e.message || e);
  }
}

console.log("overworld structural + pure tests\n");

// ── 1. Real assets present ──────────────────────────────────────────
await check("rogue_hooded.glb exists under public/models", () => {
  const p = path.join(frontendRoot, "public/models/rogue_hooded.glb");
  assert.ok(existsSync(p), `missing ${p}`);
  const size = readFileSync(p).length;
  assert.ok(size > 100_000, `glb too small (${size})`);
});

// ── 2. Scene mounts grass + player (shipped source) ─────────────────
await check("Scene.tsx mounts GrassBlades, Boulders, RogueCharacter path", () => {
  const body = readFileSync(src("overworld/Scene.tsx"), "utf8");
  assert.match(body, /GrassBlades/);
  assert.match(body, /Boulders/);
  assert.match(body, /ForestBelt/);
  assert.match(body, /RogueCharacter|PlayerCharacter/);
  assert.match(body, /LivePlayer/);
  assert.match(body, /ENTER_DIST|MOVE_SPEED/);
  // Walk / near-stop logic still present
  assert.match(body, /onNearChange/);
  assert.match(body, /autoWalkRef/);
});

await check("WorldMap.tsx still mounts OverworldScene Canvas", () => {
  const body = readFileSync(src("components/WorldMap.tsx"), "utf8");
  assert.match(body, /OverworldScene/);
  assert.match(body, /Canvas/);
  assert.match(body, /keysRef/);
  assert.match(body, /WASD|walk/i);
});

await check("props.tsx has dense dual-layer grass + BOTW palette", () => {
  const body = readFileSync(src("overworld/props.tsx"), "utf8");
  assert.match(body, /GRASS_COUNT_TALL/);
  assert.match(body, /GRASS_COUNT_SHORT/);
  assert.match(body, /grassMaterial/);
  assert.match(body, /uWindAmp|wind/);
  // Tall + short layers
  assert.ok(
    /22000|18000|GRASS_COUNT/.test(body),
    "expected high grass instance counts"
  );
});

await check("PlayerCharacter uses rogue recolor pipeline", () => {
  const body = readFileSync(src("overworld/PlayerCharacter.tsx"), "utf8");
  assert.match(body, /rogue_hooded\.glb/);
  assert.match(body, /recolorRogueImageData|recolorRogueTexture/);
  assert.match(body, /HIDDEN_MESH_PATTERN/);
  assert.match(body, /Running_A|Idle/);
});

// ── 3. Pure rogue recolor (shipped function, type-stripped for Node) ─
await check("rogueMaterials.recolorRoguePixel crushes neon green to dark muted", async () => {
  const { buildSync } = await import("esbuild");
  const outFile = path.join(
    process.env.SCRATCH ||
      "/var/folders/c_/sfcqw87j1cqdlb0nnqq5ht3m0000gn/T/grok-goal-1fa06731d3ed/implementer",
    "rogueMaterials.test.bundle.mjs"
  );
  buildSync({
    entryPoints: [src("overworld/rogueMaterials.ts")],
    bundle: true,
    format: "esm",
    platform: "neutral",
    outfile: outFile,
    logLevel: "silent",
  });
  const {
    recolorRoguePixel,
    recolorRogueImageData,
    ROGUE_FALLBACK_HEX,
  } = await import(pathToFileURL(outFile).href + `?t=${Date.now()}`);

  assert.ok(ROGUE_FALLBACK_HEX, "fallback hex defined");

  // Bright KayKit green cloak sample
  const [r, g, b] = recolorRoguePixel(80, 200, 60);
  assert.ok(g < 160, `green channel should drop (${g})`);
  assert.ok(r < 160 && b < 160, "should be muted");
  // Not pure black — keep cloak readable
  assert.ok(r + g + b > 60, `too dark (${r},${g},${b})`);
  // Not still neon green-dominant cartoon
  assert.ok(
    !(g > r * 1.4 && g > b * 1.4),
    `still neon-green dominant (${r},${g},${b})`
  );

  // ImageData path
  const data = new Uint8ClampedArray([80, 200, 60, 255, 0, 0, 0, 0]);
  recolorRogueImageData({ data, width: 2, height: 1 });
  assert.ok(data[1] < 160, "imageData green remapped");
  assert.strictEqual(data[7], 0, "transparent pixel alpha untouched");
});

// layout pure helpers — load real shipped layout.ts via esbuild bundle
await check("layout.ts hash01 + layoutStops + ENTER_DIST still resolve stops", async () => {
  const { buildSync } = await import("esbuild");
  const outFile = path.join(
    process.env.SCRATCH ||
      "/var/folders/c_/sfcqw87j1cqdlb0nnqq5ht3m0000gn/T/grok-goal-1fa06731d3ed/implementer",
    "layout.test.bundle.mjs"
  );
  buildSync({
    entryPoints: [src("overworld/layout.ts")],
    bundle: true,
    format: "esm",
    platform: "neutral",
    outfile: outFile,
    logLevel: "silent",
  });
  const api = await import(pathToFileURL(outFile).href + `?t=${Date.now()}`);
  assert.ok(api.WORLD_W > 0 && api.WORLD_D > 0);
  assert.ok(api.ENTER_DIST > 1, "ENTER_DIST usable");
  assert.ok(api.MOVE_SPEED > 1, "MOVE_SPEED usable");

  const a = api.hash01("overworld");
  const b = api.hash01("overworld");
  const c = api.hash01("other");
  assert.strictEqual(a, b, "hash deterministic");
  assert.notStrictEqual(a, c, "hash differs by seed");
  assert.ok(a >= 0 && a < 1, "hash in [0,1)");

  const stops = [
    {
      kind: "world",
      node: {
        name: "A",
        key: "A",
        children: [],
        topics: [],
        count: 1,
        built: 0,
        reviewed: 0,
      },
      id: "world:A",
    },
    {
      kind: "world",
      node: {
        name: "B",
        key: "B",
        children: [],
        topics: [],
        count: 1,
        built: 0,
        reviewed: 0,
      },
      id: "world:B",
    },
    {
      kind: "level",
      topic: { id: "t1", title: "Topic", planStatus: "built" },
      id: "level:t1",
    },
  ];
  const { placed, edges } = api.layoutStops(stops);
  assert.strictEqual(placed.length, 3, "3 stops placed");
  assert.ok(edges.length >= 2, "edges connect stops");
  for (const p of placed) {
    assert.ok(Math.abs(p.x) < api.WORLD_W, "x in world");
    assert.ok(Math.abs(p.z) < api.WORLD_D, "z in world");
  }
  const keys = new Set(
    placed.map((p) => `${p.x.toFixed(2)},${p.z.toFixed(2)}`)
  );
  assert.strictEqual(keys.size, 3, "stops not stacked");

  // pathSamples still produces walkable trail points
  const samples = api.pathSamples(0, 0, 4, 3, "trail", 10);
  assert.ok(samples.length >= 8, "path has samples");
  assert.ok(
    Math.hypot(samples[0].x, samples[0].z) < 0.5,
    "path starts near origin"
  );
});

console.log(failed ? `\n${failed} failed` : "\nall passed");
process.exit(failed ? 1 : 0);
