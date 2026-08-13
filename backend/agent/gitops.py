"""Git helpers for per-concept repos (history, revert, served hash)."""


from __future__ import annotations


import re


import subprocess


from pathlib import Path


from typing import List


# --- Git history ------------------------------------------------------------
# Every Grok change to an app is captured as a descriptive commit so a
# bad change can be rolled back. Commits are made by the backend (deterministic),
# not the agent — the house rules forbid the agent from touching git.
def _git(args: List[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)


def _git_ensure_repo(cwd: Path) -> None:
    if (cwd / ".git").exists():
        return
    _git(["init", "-q"], cwd)
    _git(["config", "user.email", "factory@concept.local"], cwd)
    _git(["config", "user.name", "Concept Factory"], cwd)
    # Keep generated/heavy dirs out of history so commits are just source.
    gi = cwd / ".gitignore"
    lines = gi.read_text().splitlines() if gi.exists() else []
    for pat in ("node_modules", "dist", ".cflogs"):
        if pat not in lines:
            lines.append(pat)
    gi.write_text("\n".join(lines) + "\n")


def git_commit(cwd: Path, message: str) -> bool:
    """Snapshot the app's source as a commit (inits the repo on first use).

    Returns True if a commit was made, False if nothing changed.
    """
    _git_ensure_repo(cwd)
    _git(["add", "-A"], cwd)
    # dist/ is gitignored (it's generated), but we deliberately version the built
    # bundle too so any past version can be re-served by a plain git restore — no
    # Grok, no npm rebuild needed to switch versions.
    if (cwd / "dist").exists():
        _git(["add", "-f", "dist"], cwd)
    if _git(["diff", "--cached", "--quiet"], cwd).returncode == 0:
        return False  # nothing staged
    _git(["commit", "-q", "-m", message], cwd)
    return True


def has_committed_dist(cwd: Path, ref: str) -> bool:
    """True if commit ``ref`` carries a built bundle, i.e. it can be served by a
    plain git restore without rebuilding."""
    if not (cwd / ".git").exists():
        return False
    return _git(["cat-file", "-e", f"{ref}:dist/index.html"], cwd).returncode == 0


def served_hash(cwd: Path) -> str:
    """Full hash of the commit whose version is currently being served.

    Usually that's HEAD, but a revert records a synthetic ``Revert to <short>``
    commit at the tip whose content is really an earlier version — and those
    synthetic commits are hidden from the history — so resolve through it to the
    real commit the user is actually looking at.
    """
    if not (cwd / ".git").exists():
        return ""
    head = _git(["rev-parse", "HEAD"], cwd).stdout.strip()
    if not head:
        return ""
    subject = _git(["log", "-1", "--pretty=format:%s", "HEAD"], cwd).stdout.strip()
    m = re.match(r"^Revert to ([0-9a-f]{4,40})$", subject)
    if m:
        resolved = _git(
            ["rev-parse", "--verify", "--quiet", m.group(1) + "^{commit}"], cwd
        ).stdout.strip()
        if resolved:
            return resolved
    return head


# Auto-generated maintenance commits (reverts, protective snapshots) that the
# system creates for bookkeeping — not real user-facing changes, so they're
# hidden from the Versions history.
_INTERNAL_COMMIT_PREFIXES = ("Revert to ", "Snapshot before ")


def git_log(cwd: Path, n: int = 100) -> list:
    if not (cwd / ".git").exists():
        return []
    out = _git(["log", f"-{n}", "--pretty=format:%H%x1f%s%x1f%cI"], cwd).stdout
    commits = []
    for line in out.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 3:
            continue
        message = parts[1]
        if message.startswith(_INTERNAL_COMMIT_PREFIXES):
            continue
        commits.append({"hash": parts[0], "message": message, "date": parts[2]})
    return commits


def git_revert_to(cwd: Path, target: str) -> bool:
    """Restore the source to a prior commit as a NEW commit (history preserved
    so you can still go forward again)."""
    if not (cwd / ".git").exists():
        return False
    old = _git(["rev-parse", "HEAD"], cwd).stdout.strip()
    if not old or target == old:
        return False
    _git(["reset", "--hard", target], cwd)   # worktree + index -> target
    _git(["reset", "--soft", old], cwd)       # move HEAD back to tip, keep content
    if _git(["diff", "--cached", "--quiet"], cwd).returncode != 0:
        _git(["commit", "-q", "-m", f"Revert to {target[:8]}"], cwd)
    return True
