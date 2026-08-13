"""Pytest env guards: keep tests hermetic.

- CF_SETTINGS_SYNC_CLI=0 — PUT /api/settings must not write ~/.claude or ~/.grok
- CF_SETTINGS_WARM=0     — TestClient startup must not spawn discovery CLIs
Tests that exercise sync explicitly override these via monkeypatch/env.

Also puts backend/ on sys.path so tests import the app modules directly.
"""
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

os.environ.setdefault("CF_SETTINGS_SYNC_CLI", "0")
os.environ.setdefault("CF_SETTINGS_WARM", "0")
