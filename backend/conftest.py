"""Pytest env guards: keep tests hermetic.

- CF_SETTINGS_SYNC_CLI=0 — PUT /api/settings must not write ~/.claude or ~/.grok
- CF_SETTINGS_WARM=0     — TestClient startup must not spawn discovery CLIs
Tests that exercise sync explicitly override these via monkeypatch/env.
"""
import os

os.environ.setdefault("CF_SETTINGS_SYNC_CLI", "0")
os.environ.setdefault("CF_SETTINGS_WARM", "0")
