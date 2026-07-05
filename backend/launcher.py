"""Launcher for full-stack concept apps.

Some copied concepts (e.g. ``regex``, ``thousand-concurrent-connections``) are
not single static bundles — they have their own backends and hardcode ports
that collide with Concept Factory (8000 / 5173). Rather than serve them
statically, we run them on demand from copy-on-write runtime copies on remapped
ports, and the card links to the running app.

Design mirrors the rest of the backend: disk/process state is the source of
truth, everything is best-effort and self-reporting, and no source repo is
mutated (we only ever touch the runtime copy under ``fullstack/``).
"""
from __future__ import annotations

import os
import re
import signal
import socket
import subprocess
import threading
from pathlib import Path
from typing import List

BACKEND_DIR = Path(__file__).parent
CF_ROOT = BACKEND_DIR.parent
SRC = CF_ROOT.parent / "software-engineering"
RUNTIME = CF_ROOT / "fullstack"
RUNTIME.mkdir(exist_ok=True)

# Each full-stack concept, its card title, and the ports we run it on. Ports are
# in a private range so they never collide with Concept Factory or each other.
SPECS = {
    "regex": {
        "title": "Regular Expressions",
        "blurb": "Pattern Drop — a timed game where you type strings that match falling regex patterns.",
        "fe_port": 7201,
        "be_port": 7101,
        "needs": None,
        "ready_timeout": 120,
    },
    "thousand-concurrent-connections": {
        "title": "1,000 Concurrent Connections",
        "blurb": "Compare naive, NIO, and virtual-thread servers handling thousands of live connections.",
        "fe_port": 7202,
        "be_port": None,  # runs its own fixed backend ports (808x/908x/8090)
        "needs": "java21",
        "ready_timeout": 360,  # first run does mvn package + venv + npm installs
    },
}

JAVA21_HOME = "/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home"
JAVA21_BIN = "/opt/homebrew/opt/openjdk@21/bin"

# slug -> {"status", "url", "procs": [Popen], "error"}
_runs: dict = {}
_lock = threading.Lock()


def _url(slug: str) -> str:
    return f"http://localhost:{SPECS[slug]['fe_port']}/"


def _port_open(port: int) -> bool:
    # Try every address localhost resolves to — Vite binds ::1 (IPv6) on macOS
    # while an IPv4-only check to 127.0.0.1 would miss it.
    try:
        with socket.create_connection(("localhost", port), timeout=0.5):
            return True
    except OSError:
        return False


def _java_major() -> int:
    try:
        out = subprocess.run(["java", "-version"], capture_output=True, text=True).stderr
    except FileNotFoundError:
        return 0
    m = re.search(r'version "(\d+)(?:\.(\d+))?', out)
    if not m:
        return 0
    major = int(m.group(1))
    return int(m.group(2) or 0) if major == 1 else major  # "1.8" -> 8


def _java21_ok() -> bool:
    """Java 21 is available if the Homebrew keg exists or default java is >=21."""
    return Path(JAVA21_BIN, "java").exists() or _java_major() >= 21


def _java21_env() -> dict:
    """Env that puts Java 21 first, matching what the concept's start.sh expects."""
    env = dict(os.environ)
    if Path(JAVA21_BIN, "java").exists():
        env["JAVA_HOME"] = JAVA21_HOME
        env["PATH"] = f"{JAVA21_BIN}:{env.get('PATH', '')}"
    return env


def _log_tail(dest: Path, name: str, n: int = 12) -> str:
    p = dest / ".cflogs" / f"{name}.log"
    if not p.exists():
        return ""
    return "\n".join(p.read_text(errors="replace").splitlines()[-n:])


# --- Runtime copy preparation ----------------------------------------------
def _prepare(slug: str) -> Path:
    dest = RUNTIME / slug
    if not dest.exists():
        src = SRC / slug
        if subprocess.run(["cp", "-Rc", str(src), str(dest)]).returncode != 0:
            subprocess.run(["cp", "-R", str(src), str(dest)], check=True)
        for junk in [dest / ".git"]:
            subprocess.run(["rm", "-rf", str(junk)])
        # Point the frontend's /api proxy at our remapped backend port.
        be = SPECS[slug]["be_port"]
        if be:
            for cfg in (dest / "frontend").glob("vite.config.*"):
                txt = cfg.read_text()
                if "localhost:8000" in txt:
                    cfg.write_text(txt.replace("localhost:8000", f"localhost:{be}"))
        # Make start.sh launch the frontend on our remapped port, not :5173.
        sh = dest / "start.sh"
        if sh.exists():
            txt = sh.read_text()
            fe = SPECS[slug]["fe_port"]
            if "npm run dev &" in txt:
                sh.write_text(txt.replace(
                    "npm run dev &",
                    f"npm run dev -- --port {fe} --strictPort &",
                ))
    return dest


def _ensure_python_backend(dest: Path) -> List[str]:
    """Return the python executable for the concept's backend venv, creating it
    if the copied one doesn't resolve."""
    py = dest / "backend" / ".venv" / "bin" / "python"
    ok = py.exists() and subprocess.run(
        [str(py), "-c", "import uvicorn"], capture_output=True
    ).returncode == 0
    if not ok:
        venv = dest / "backend" / ".venv"
        subprocess.run(["rm", "-rf", str(venv)])
        subprocess.run(["python3", "-m", "venv", str(venv)], check=True)
        subprocess.run(
            [str(py), "-m", "pip", "install", "-q", "-r",
             str(dest / "backend" / "requirements.txt")],
            check=True,
        )
    return str(py)


# --- Launch / stop ----------------------------------------------------------
def _spawn(cmd: List[str], cwd: Path, dest: Path, name: str, env: dict = None) -> subprocess.Popen:
    # Own session so we can kill the whole process tree on stop; capture output
    # to a per-process log so failures are diagnosable (and shown in the UI).
    logs = dest / ".cflogs"
    logs.mkdir(exist_ok=True)
    log = open(logs / f"{name}.log", "w")
    return subprocess.Popen(
        cmd, cwd=str(cwd), stdout=log, stderr=subprocess.STDOUT,
        start_new_session=True, env=env,
    )


def _launch_regex(dest: Path, spec: dict) -> List[subprocess.Popen]:
    py = _ensure_python_backend(dest)
    fe = dest / "frontend"
    if not (fe / "node_modules").exists():
        subprocess.run(["npm", "install"], cwd=str(fe), capture_output=True, timeout=600)
    return [
        _spawn([py, "-m", "uvicorn", "main:app", "--port", str(spec["be_port"])],
               dest / "backend", dest, "backend"),
        _spawn(["npm", "run", "dev", "--", "--port", str(spec["fe_port"]), "--strictPort"],
               fe, dest, "frontend"),
    ]


def _launch_thousand(dest: Path, spec: dict) -> List[subprocess.Popen]:
    # start.sh orchestrates Java + Python servers + proxy + frontend. Run its
    # frontend on our port (patched in _prepare); the rest use its fixed ports.
    return [_spawn(["bash", "start.sh"], dest, dest, "app", env=_java21_env())]


def launch(slug: str) -> dict:
    if slug not in SPECS:
        return {"status": "error", "error": "Unknown concept", "url": ""}
    with _lock:
        run = _runs.get(slug)
        if run and run["status"] in ("starting", "running"):
            return _public(slug)

    spec = SPECS[slug]
    if spec["needs"] == "java21" and not _java21_ok():
        result = {"status": "error", "url": "",
                  "error": f"Needs Java 21 for virtual threads (found {_java_major() or 'none'})."}
        with _lock:
            _runs[slug] = {**result, "procs": []}
        return result

    try:
        dest = _prepare(slug)
        procs = _launch_regex(dest, spec) if slug == "regex" else _launch_thousand(dest, spec)
    except Exception as exc:  # noqa: BLE001 - surface any prep/launch failure
        with _lock:
            _runs[slug] = {"status": "error", "url": "", "error": str(exc)[:300], "procs": []}
        return _public(slug)

    with _lock:
        _runs[slug] = {"status": "starting", "url": _url(slug), "error": "",
                       "procs": procs, "dest": dest}
    threading.Thread(target=_await_ready, args=(slug,), daemon=True).start()
    return _public(slug)


def _await_ready(slug: str) -> None:
    port = SPECS[slug]["fe_port"]
    timeout = SPECS[slug].get("ready_timeout", 120)
    for _ in range(timeout * 2):
        if _port_open(port):
            with _lock:
                if slug in _runs:
                    _runs[slug]["status"] = "running"
            return
        with _lock:
            procs = _runs.get(slug, {}).get("procs", [])
            dest = _runs.get(slug, {}).get("dest")
        # Fail fast only if every process died (e.g. a crash on startup).
        if procs and all(p.poll() is not None for p in procs):
            break
        threading.Event().wait(0.5)
    tail = _log_tail(dest, "frontend") or _log_tail(dest, "app") if dest else ""
    with _lock:
        if slug in _runs and _runs[slug]["status"] != "running":
            _runs[slug]["status"] = "error"
            _runs[slug]["error"] = ("App did not become reachable in time. "
                                    + (tail[-260:] if tail else "")).strip()


def stop(slug: str) -> dict:
    with _lock:
        run = _runs.get(slug)
        procs = run["procs"] if run else []
    for p in procs:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    with _lock:
        _runs[slug] = {"status": "stopped", "url": "", "error": "", "procs": []}
    return _public(slug)


def _public(slug: str) -> dict:
    run = _runs.get(slug, {"status": "stopped", "url": "", "error": ""})
    return {"status": run["status"], "url": run["url"], "error": run.get("error", "")}


def status(slug: str) -> dict:
    return _public(slug)
