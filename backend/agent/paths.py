"""Filesystem anchors for the agent package.

Everything is resolved from the backend/ directory (this package's parent) so
moving code between modules never silently repoints workspace or config files.
"""
from __future__ import annotations

from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent

TEMPLATE_DIR = REPO_ROOT / "meta-agent" / "template"

WORKSPACE = BACKEND_DIR / "workspace"
WORKSPACE.mkdir(exist_ok=True)

# Global factory settings (Grok options). Separate from data.json so topic
# cards and driver config don't thrash the same lock/file.
SETTINGS_FILE = BACKEND_DIR / "settings.json"

_HELP_CACHE_FILE = BACKEND_DIR / ".cli_help_cache.json"

USAGE_FILE = BACKEND_DIR / "usage.json"
