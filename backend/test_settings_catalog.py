"""Tests for live CLI settings-catalog discovery + TTL cache.

Primary path drives the shipped ``agent.get_settings_catalog`` /
``run_discovery_cli`` / parsers. When real ``grok`` / ``claude`` binaries are
on PATH, live discovery is exercised and asserted to include models the static
UI used to miss (e.g. grok-4.5, fable).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

BACKEND = Path(__file__).resolve().parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import agent  # noqa: E402

try:
    from fastapi.testclient import TestClient
    from main import app
except ImportError:  # pragma: no cover
    TestClient = None  # type: ignore
    app = None  # type: ignore

HAS_GROK = bool(shutil.which("grok") or (agent.GROK_BIN and Path(agent.GROK_BIN).is_file()))
HAS_CLAUDE = bool(
    shutil.which("claude") or (agent.CLAUDE_BIN and Path(agent.CLAUDE_BIN).is_file())
)

# Captured from real CLIs on this machine (also used as parse fixtures).
FIXTURE_GROK_MODELS = """\
You are using XAI_API_KEY.

Default model: grok-4.5

Available models:
  - grok-4.20-0309-non-reasoning
  - grok-4.20-0309-reasoning
  - grok-4.3
  * grok-4.5 (default)
  - grok-build-0.1
"""

FIXTURE_CLAUDE_MODEL = """\
Current model: Haiku 4.5
Usage: /model <name>. Available: sonnet, opus, haiku, fable, best, sonnet[1m], opus[1m], fable[1m], opusplan, default, or a full model ID.
"""

FIXTURE_GROK_HELP = """\
      --permission-mode <MODE>
          Permission mode [possible values: default, acceptEdits, auto, dontAsk, bypassPermissions, plan]
      --reasoning-effort <EFFORT>
          Reasoning effort for reasoning models [aliases: --effort]
"""

FIXTURE_CLAUDE_HELP = """\
  --effort <level>                      Effort level for the current session
                                        (low, medium, high, xhigh, max)
  --permission-mode <mode>              Permission mode to use for the session
                                        (choices: "acceptEdits", "auto",
                                        "bypassPermissions", "manual",
                                        "dontAsk", "plan")
  --model <model>                       aliases e.g. 'fable', 'opus', or 'sonnet'
"""


class ParserTests(unittest.TestCase):
    def test_parse_grok_models_includes_45(self) -> None:
        parsed = agent.parse_grok_models_output(FIXTURE_GROK_MODELS)
        values = [m["value"] for m in parsed["models"] if m["value"]]
        self.assertIn("grok-4.5", values)
        self.assertEqual(parsed["default"], "grok-4.5")
        self.assertEqual(parsed["currentModel"], "grok-4.5")
        # No empty "CLI default" placeholder row
        self.assertTrue(all(m["value"] for m in parsed["models"]))

    def test_parse_claude_models_includes_fable(self) -> None:
        # Fixture is haiku current — map to alias
        text = (
            "Current model: Haiku 4.5\n"
            "Usage: /model <name>. Available: sonnet, opus, haiku, fable, best, "
            "or a full model ID.\n"
        )
        parsed = agent.parse_claude_models_output(text)
        values = [m["value"] for m in parsed["models"]]
        self.assertIn("fable", values)
        self.assertIn("sonnet", values)
        self.assertEqual(parsed["currentModel"], "haiku")

    def test_parse_claude_current_fable(self) -> None:
        text = (
            "Current model: Fable 5\n"
            "Usage: /model <name>. Available: sonnet, opus, haiku, fable, best, "
            "sonnet[1m], opus[1m], fable[1m], opusplan, default, or a full model ID.\n"
        )
        parsed = agent.parse_claude_models_output(text)
        self.assertEqual(parsed["currentModel"], "fable")
        self.assertEqual(parsed["currentLabel"], "Fable 5")

    def test_map_settings_model_full_id(self) -> None:
        alias = agent.map_claude_current_to_alias(
            "Fable 5",
            ["sonnet", "opus", "haiku", "fable", "fable[1m]"],
            settings_model="claude-fable-5[1m]",
        )
        self.assertEqual(alias, "fable[1m]")

    def test_resolve_model_selection(self) -> None:
        # Empty / bootstrap sonnet → CLI current
        self.assertEqual(
            agent.resolve_model_selection("", "fable", driver="claude"),
            "fable",
        )
        self.assertEqual(
            agent.resolve_model_selection("sonnet", "fable", driver="claude"),
            "fable",
        )
        # Explicit non-bootstrap override kept unless follow_cli
        self.assertEqual(
            agent.resolve_model_selection("opus", "fable", driver="claude"),
            "opus",
        )
        self.assertEqual(
            agent.resolve_model_selection(
                "opus", "fable", driver="claude", follow_cli=True
            ),
            "fable",
        )
        # Grok empty → concrete current, not ""
        self.assertEqual(
            agent.resolve_model_selection("", "grok-4.5", driver="grok"),
            "grok-4.5",
        )

    def test_parse_help_enums(self) -> None:
        gperm = agent.parse_help_possible_values(FIXTURE_GROK_HELP, "--permission-mode")
        self.assertIn("bypassPermissions", gperm)
        cperm = agent.parse_help_possible_values(FIXTURE_CLAUDE_HELP, "--permission-mode")
        self.assertIn("manual", cperm)
        effort = agent.parse_help_effort_levels(FIXTURE_CLAUDE_HELP)
        self.assertEqual(effort, ["low", "medium", "high", "xhigh", "max"])


class CatalogPollTests(unittest.TestCase):
    """TTL cache + in-flight coalesce for get_settings_catalog."""

    def setUp(self) -> None:
        agent.clear_settings_catalog_cache()
        agent.reset_cli_spawn_count()

    def tearDown(self) -> None:
        agent.clear_settings_catalog_cache()

    def _fake_discover(self) -> dict:
        return {
            "fetchedAt": time.time(),
            "fetchedAtIso": "2026-01-01T00:00:00Z",
            "elapsedMs": 1.0,
            "ttlSeconds": agent.CATALOG_TTL_SECONDS,
            "source": "live-cli",
            "cache": "none",
            "grok": {
                "models": [{"value": "grok-4.5", "label": "grok-4.5"}],
                "currentModel": "grok-4.5",
                "permissionModes": [],
                "reasoningEfforts": [{"value": "", "label": "Default"}],
            },
            "claude": {
                "models": [{"value": "fable", "label": "fable"}],
                "currentModel": "fable",
                "permissionModes": [],
                "efforts": [{"value": "", "label": "Default"}],
            },
        }

    def test_ttl_reuses_second_call(self) -> None:
        """Within TTL, second sequential call must hit memory cache."""
        calls = {"n": 0}

        def fake(*args, **kwargs) -> dict:
            calls["n"] += 1
            return self._fake_discover()

        with mock.patch.object(agent, "discover_settings_catalog", side_effect=fake):
            a = agent.get_settings_catalog()
            self.assertEqual(calls["n"], 1)
            self.assertEqual(a.get("cache"), "none")
            b = agent.get_settings_catalog()
            self.assertEqual(calls["n"], 1, "TTL: second call must not re-discover")
            self.assertEqual(b.get("cache"), "memory")
            c = agent.get_settings_catalog(force=True)
            self.assertEqual(calls["n"], 2, "force must re-discover")
            self.assertEqual(c.get("cache"), "none")

    def test_coalesce_concurrent_calls(self) -> None:
        """Parallel callers share one in-flight discovery."""
        calls = {"n": 0}
        barrier = threading.Barrier(2)

        def fake(*args, **kwargs) -> dict:
            calls["n"] += 1
            time.sleep(0.15)
            return self._fake_discover()

        results: list = []

        def worker() -> None:
            barrier.wait()
            results.append(agent.get_settings_catalog())

        with mock.patch.object(agent, "discover_settings_catalog", side_effect=fake):
            t1 = threading.Thread(target=worker)
            t2 = threading.Thread(target=worker)
            t1.start()
            t2.start()
            t1.join()
            t2.join()
        self.assertEqual(calls["n"], 1, "concurrent calls must coalesce")
        self.assertEqual(len(results), 2)
        caches = {r.get("cache") for r in results}
        self.assertTrue(caches <= {"none", "coalesced", "memory"})


@unittest.skipUnless(HAS_GROK and HAS_CLAUDE, "both CLIs required for live discovery")
class LiveDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        agent.clear_settings_catalog_cache()
        agent.reset_cli_spawn_count()

    def tearDown(self) -> None:
        agent.clear_settings_catalog_cache()

    def test_live_cli_spawn_and_models(self) -> None:
        """Discovery returns live models; second call hits TTL cache."""
        before = agent.get_cli_spawn_count()
        cat = agent.get_settings_catalog()
        after = agent.get_cli_spawn_count()
        # At least help probes (+ maybe claude /model pty); grok models may be file cache
        self.assertGreaterEqual(after - before, 1)
        self.assertIn(cat.get("source"), ("live", "live-cli"))

        g_values = [m["value"] for m in cat["grok"]["models"] if m["value"]]
        c_values = [m["value"] for m in cat["claude"]["models"] if m["value"]]
        self.assertTrue(g_values, "Grok model list empty")
        self.assertTrue(c_values, "Claude model list empty")
        self.assertIn("grok-4.5", g_values)
        self.assertTrue(cat["grok"].get("currentModel"))
        self.assertTrue(cat["claude"].get("currentModel"))

        c_probe = cat["claude"]["probes"]["models"]["argv"]
        # Claude must NOT pin --model on the list probe
        self.assertNotIn("--model", c_probe)

        # TTL: second call reuses memory without extra spawns
        sp = agent.get_cli_spawn_count()
        hit = agent.get_settings_catalog()
        self.assertEqual(agent.get_cli_spawn_count(), sp)
        self.assertEqual(hit.get("cache"), "memory")

    def test_run_discovery_cli_spawns_grok_models(self) -> None:
        """Direct unit under test: run_discovery_cli executes real grok models."""
        r = agent.run_discovery_cli([agent.GROK_BIN, "models"])
        self.assertEqual(r["returncode"], 0)
        self.assertIn("grok-4.5", r["stdout"])
        parsed = agent.parse_grok_models_output(r["stdout"])
        self.assertTrue(any(m["value"] == "grok-4.5" for m in parsed["models"]))
        self.assertEqual(parsed["currentModel"], "grok-4.5")


@unittest.skipIf(TestClient is None, "fastapi TestClient unavailable")
class CatalogApiTests(unittest.TestCase):
    def setUp(self) -> None:
        agent.clear_settings_catalog_cache()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        agent.clear_settings_catalog_cache()

    def test_catalog_endpoint_uses_discovery(self) -> None:
        fake = {
            "fetchedAt": time.time(),
            "fetchedAtIso": "2026-01-01T00:00:00Z",
            "elapsedMs": 12.0,
            "ttlSeconds": 3600,
            "source": "live-cli",
            "cache": "none",
            "ageSeconds": 0,
            "grok": {
                "models": [
                    {"value": "grok-4.5", "label": "grok-4.5 (current)"},
                ],
                "currentModel": "grok-4.5",
                "permissionModes": [{"value": "auto", "label": "Auto"}],
                "reasoningEfforts": [{"value": "", "label": "Default"}],
                "probes": {"models": {"argv": ["file", "models_cache.json"]}},
            },
            "claude": {
                "models": [{"value": "fable", "label": "fable"}],
                "currentModel": "fable",
                "permissionModes": [{"value": "plan", "label": "Plan"}],
                "efforts": [{"value": "low", "label": "Low"}],
                "probes": {"models": {"argv": ["claude", "-p", "/model"]}},
            },
        }
        with mock.patch.object(agent, "get_settings_catalog", return_value=fake) as m:
            r = self.client.get("/api/settings/catalog")
            self.assertEqual(r.status_code, 200)
            body = r.json()
            self.assertEqual(body["grok"]["models"][0]["value"], "grok-4.5")
            self.assertEqual(body["claude"]["models"][0]["value"], "fable")
            m.assert_called()
            r2 = self.client.post("/api/settings/catalog/refresh")
            self.assertEqual(r2.status_code, 200)
            payload = r2.json()
            self.assertIn("catalog", payload)
            self.assertIn("settings", payload)
            # Bootstrap is optional; when present must return catalog+settings
            r3 = self.client.get("/api/settings/bootstrap")
            self.assertEqual(r3.status_code, 200)
            boot = r3.json()
            self.assertIn("catalog", boot)
            self.assertIn("settings", boot)

    def test_settings_endpoint_is_fast_without_catalog(self) -> None:
        """GET /api/settings must not depend on discovery (modal paints form)."""
        with mock.patch.object(
            agent, "get_settings_catalog", side_effect=AssertionError("should not poll")
        ):
            r = self.client.get("/api/settings")
            self.assertEqual(r.status_code, 200)
            body = r.json()
            self.assertIn("driver", body)
            self.assertIn("grok", body)
            self.assertIn("claude", body)


class FrontendNoHardcodedModelsTests(unittest.TestCase):
    def test_settings_modal_has_no_static_model_arrays(self) -> None:
        root = BACKEND.parent / "frontend" / "src" / "components" / "SettingsModal.tsx"
        src = root.read_text()
        # Hard-coded model ID tables must not reappear.
        for needle in (
            "GROK_MODELS",
            "CLAUDE_MODELS",
            "grok-3-mini",
            "claude-sonnet-4-5",
            "claude-opus-4-5",
        ):
            self.assertNotIn(needle, src)
        # Open path must use reliable dual endpoints (not bootstrap-only).
        self.assertIn("getSettings", src)
        self.assertIn("getSettingsCatalog", src)
        self.assertNotIn("bootstrapSettings", src)
        self.assertIn("catalog?.grok", src)
        self.assertIn("catalog?.claude", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
