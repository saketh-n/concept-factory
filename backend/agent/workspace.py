"""Per-topic workspace folders under backend/workspace/."""


from __future__ import annotations


import re


import shutil


from pathlib import Path


from typing import Optional


from .paths import TEMPLATE_DIR, WORKSPACE


from .gitops import _git


PLAN_FILE = "PLAN.md"


def slugify(title: str, taken: set) -> str:
    """kebab-case slug for a topic title, made unique against ``taken``."""
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48] or "topic"
    slug = base
    i = 2
    while slug in taken:
        slug = f"{base}-{i}"
        i += 1
    return slug


def topic_dir(slug: str) -> Path:
    path = WORKSPACE / slug
    path.mkdir(parents=True, exist_ok=True)
    return path


def is_built(slug: str) -> bool:
    """True if a servable production bundle exists on disk for this slug.

    This is the source of truth for "built" — status reconciliation checks the
    workspace rather than trusting a possibly-stale persisted enum.
    """
    return bool(slug) and (WORKSPACE / slug / "dist" / "index.html").is_file()


def copy_template(dest: Path) -> None:
    """Copy the concept-template into a topic folder for building.

    Skips node_modules / build output; leaves PLAN.md in place.
    """
    if not TEMPLATE_DIR.exists():
        return
    ignore = shutil.ignore_patterns("node_modules", "dist", ".git", "*.log")
    for item in TEMPLATE_DIR.iterdir():
        target = dest / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True, ignore=ignore)
        else:
            shutil.copy2(item, target)


def seed_history(dest: Path, src: Optional[Path]) -> None:
    """Adopt a concept's real git history into its working copy.

    The workspace/runtime copies were made without .git, so review/revert
    would otherwise operate on a phantom timeline. This copies the source
    repo's .git in ONCE, then never touches it again.

    Invariant: if ``dest`` already has history, do nothing — we never replace
    or rewrite an existing timeline (that was the old overwriting bug). A
    missing or history-less ``src`` is tolerated: the concept simply starts
    its history at the first backend commit.
    """
    if (dest / ".git").exists():
        return  # already has a timeline — never overwrite it
    if not src or not (src / ".git").exists():
        return  # nothing to adopt; git_commit will init on first snapshot
    shutil.copytree(src / ".git", dest / ".git")
    # The copied index reflects src's tree, not dest's files. A mixed reset
    # realigns HEAD/index/worktree without discarding any local changes.
    _git(["reset", "--mixed", "-q", "HEAD"], dest)


def dist_base_ok(slug: str) -> bool:
    """True if the built bundle references the /concepts/<slug>/ asset base.

    A bundle built with Vite's default base ('/') will 404 its assets when
    served from the sub-path, so a False here is the signal that the bundle
    needs re-finalizing.
    """
    index = WORKSPACE / slug / "dist" / "index.html"
    if not index.is_file():
        return False
    return f"/concepts/{slug}/assets" in index.read_text()
