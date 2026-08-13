"""Post-build verification gates and servable-bundle finalization."""


from __future__ import annotations


import json


import subprocess


from pathlib import Path


from typing import Callable


# --- Serving the built concept ----------------------------------------------
def patch_router_basename(cwd: Path) -> None:
    """Give BrowserRouter a basename so the built app works under a sub-path.

    The template uses absolute routes (/learn, /test) with a plain
    <BrowserRouter>; served from /concepts/<slug>/ that breaks unless the
    router knows its base. import.meta.env.BASE_URL matches the Vite --base.
    """
    main = cwd / "src" / "main.tsx"
    if not main.exists():
        return
    txt = main.read_text()
    if "basename=" in txt:
        return
    patched = txt.replace(
        "<BrowserRouter>",
        "<BrowserRouter basename={import.meta.env.BASE_URL}>",
    )
    if patched != txt:
        main.write_text(patched)


def finalize_build(cwd: Path, base: str, on_line: Callable[[str], None]) -> bool:
    """Produce a sub-path-correct production build we can serve from FastAPI."""
    patch_router_basename(cwd)
    if not (cwd / "node_modules").exists():
        on_line("$ npm install")
        subprocess.run(
            ["npm", "install"], cwd=str(cwd), capture_output=True, text=True, timeout=900
        )
    on_line(f"$ npm run build -- --base={base}")
    proc = subprocess.run(
        ["npm", "run", "build", "--", f"--base={base}"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=900,
    )
    ok = proc.returncode == 0 and (cwd / "dist" / "index.html").exists()
    if ok:
        on_line("✓ production build ready to serve")
    else:
        on_line((proc.stderr or proc.stdout or "build failed").strip()[-400:])
    return ok


# --- Verification gates (harness-run, never trusted to the agent) ------------
GATE_TIMEOUT = 300


# Auto-plays every game level: bundles the concept's own levels.ts +
# checkAnswer.ts with the esbuild already inside its node_modules (vite dep —
# no extra install), then feeds each level's canonical answer through the
# validator. Emits ONE JSON line on stdout.
_VALIDATOR_JS = r"""
const path = require('path');
(async () => {
  const cwd = process.cwd();
  let esbuild;
  try {
    esbuild = require(path.join(cwd, 'node_modules', 'esbuild'));
  } catch (e) {
    console.log(JSON.stringify({ status: 'skipped', detail: 'esbuild not installed (npm install first)' }));
    return;
  }
  const entry = [
    "import { LEVELS } from './src/game/levels'",
    "import { checkAnswer } from './src/game/checkAnswer'",
    "export { LEVELS, checkAnswer }",
  ].join('\n');
  const built = await esbuild.build({
    stdin: { contents: entry, resolveDir: cwd, sourcefile: 'cf-validate-entry.ts', loader: 'ts' },
    bundle: true,
    format: 'cjs',
    platform: 'node',
    write: false,
    logLevel: 'silent',
    external: ['react', 'react-dom', 'react-router-dom', 'framer-motion'],
  });
  const mod = { exports: {} };
  new Function('module', 'exports', 'require', built.outputFiles[0].text)(mod, mod.exports, require);
  const LEVELS = mod.exports.LEVELS;
  const checkAnswer = mod.exports.checkAnswer;
  if (!Array.isArray(LEVELS) || typeof checkAnswer !== 'function') {
    console.log(JSON.stringify({ status: 'error', detail: 'LEVELS array or checkAnswer() not exported from src/game' }));
    return;
  }
  const levels = [];
  for (const level of LEVELS) {
    let ok = false;
    let reason = '';
    try {
      const answer = typeof level.answer === 'string' ? level.answer : JSON.stringify(level.answer);
      const res = checkAnswer(answer, level);
      ok = !!(res && res.ok);
      reason = ok ? '' : String((res && res.reason) || 'canonical answer rejected');
    } catch (e) {
      reason = 'validator threw: ' + String((e && e.message) || e);
    }
    levels.push({ id: level.id, topic: level.topic || '', ok, reason: reason.slice(0, 300) });
  }
  const passed = levels.filter((l) => l.ok).length;
  console.log(JSON.stringify({
    status: passed === levels.length && levels.length > 0 ? 'pass' : 'fail',
    passed,
    total: levels.length,
    levels,
  }));
})().catch((e) => {
  console.log(JSON.stringify({ status: 'error', detail: String((e && e.message) || e).slice(0, 400) }));
});
"""


def run_lint_gate(cwd: Path, on_line: Callable[[str], None]) -> dict:
    """Harness-run ``npm run lint`` gate → {status: pass|fail|skipped, detail}."""
    pkg = cwd / "package.json"
    try:
        scripts = (json.loads(pkg.read_text()).get("scripts") or {}) if pkg.is_file() else {}
    except (json.JSONDecodeError, ValueError, OSError):
        scripts = {}
    if "lint" not in scripts:
        return {"status": "skipped", "detail": "no lint script in package.json"}
    on_line("$ npm run lint")
    try:
        proc = subprocess.run(
            ["npm", "run", "lint"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=GATE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        on_line("⚠ lint timed out")
        return {"status": "fail", "detail": f"lint timed out after {GATE_TIMEOUT}s"}
    if proc.returncode == 0:
        on_line("✓ lint clean")
        return {"status": "pass", "detail": ""}
    detail = (proc.stdout or proc.stderr or "lint failed").strip()[-800:]
    on_line("✗ lint failed")
    return {"status": "fail", "detail": detail}


def run_validator_gate(cwd: Path, on_line: Callable[[str], None]) -> dict:
    """Auto-play every game level through the concept's own pure validator.

    Returns {status, passed, total, passRate, levels: [{id, topic, ok, reason}]}
    — the per-category pass rate the dashboard charts. ``skipped`` when the
    concept has no standard game module (e.g. plan-only or full-stack apps).
    """
    if not (cwd / "src" / "game" / "levels.ts").is_file():
        return {"status": "skipped", "detail": "no src/game/levels.ts"}
    script_dir = cwd / ".cflogs"
    script_dir.mkdir(exist_ok=True)
    script = script_dir / "validate.cjs"
    try:
        script.write_text(_VALIDATOR_JS)
    except OSError as e:
        return {"status": "error", "detail": f"could not write validator: {e}"}
    on_line("Auto-playing game levels through the validator…")
    try:
        proc = subprocess.run(
            ["node", str(script)],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=GATE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        on_line("⚠ validator timed out")
        return {"status": "error", "detail": f"validator timed out after {GATE_TIMEOUT}s"}
    except FileNotFoundError:
        return {"status": "skipped", "detail": "node not found on PATH"}
    result = None
    for line in reversed((proc.stdout or "").strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                result = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
    if not isinstance(result, dict):
        detail = (proc.stderr or proc.stdout or "no validator output").strip()[-800:]
        on_line("⚠ validator produced no result")
        return {"status": "error", "detail": detail}
    total = int(result.get("total") or 0)
    passed = int(result.get("passed") or 0)
    if total:
        result["passRate"] = round(passed / total, 4)
        on_line(
            f"{'✓' if result.get('status') == 'pass' else '✗'} validator: "
            f"{passed}/{total} levels pass"
        )
    else:
        on_line(f"⚠ validator: {result.get('detail') or result.get('status')}")
    return result
