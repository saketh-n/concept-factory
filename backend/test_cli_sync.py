"""Tests for widget → CLI write-back and stale-while-revalidate catalog."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

BACKEND = Path(__file__).resolve().parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import agent  # noqa: E402


class FakeHome:
    """Context manager: point Path.home() at a temp dir."""

    def __enter__(self) -> Path:
        self._tmp = tempfile.TemporaryDirectory()
        self._patch = mock.patch.object(Path, "home", return_value=Path(self._tmp.name))
        self._patch.start()
        return Path(self._tmp.name)

    def __exit__(self, *exc) -> None:
        self._patch.stop()
        self._tmp.cleanup()


class ClaudeWriteBackTests(unittest.TestCase):
    def test_creates_settings_json_when_missing(self) -> None:
        with FakeHome() as home:
            res = agent._write_claude_cli_model("haiku")
            self.assertTrue(res["ok"], res)
            self.assertTrue(res["changed"])
            data = json.loads((home / ".claude" / "settings.json").read_text())
            self.assertEqual(data["model"], "haiku")

    def test_merges_preserving_other_keys(self) -> None:
        with FakeHome() as home:
            p = home / ".claude"
            p.mkdir()
            (p / "settings.json").write_text(
                json.dumps({"model": "fable", "theme": "dark", "permissions": {"allow": ["Bash"]}})
            )
            res = agent._write_claude_cli_model("haiku")
            self.assertTrue(res["ok"] and res["changed"], res)
            data = json.loads((p / "settings.json").read_text())
            self.assertEqual(data["model"], "haiku")
            self.assertEqual(data["theme"], "dark")
            self.assertEqual(data["permissions"], {"allow": ["Bash"]})

    def test_idempotent_noop(self) -> None:
        with FakeHome():
            agent._write_claude_cli_model("haiku")
            res = agent._write_claude_cli_model("haiku")
            self.assertTrue(res["ok"])
            self.assertFalse(res["changed"])

    def test_refuses_to_clobber_invalid_json(self) -> None:
        with FakeHome() as home:
            p = home / ".claude"
            p.mkdir()
            (p / "settings.json").write_text("{not json")
            res = agent._write_claude_cli_model("haiku")
            self.assertFalse(res["ok"])
            self.assertEqual((p / "settings.json").read_text(), "{not json")


class GrokWriteBackTests(unittest.TestCase):
    def test_replaces_default_in_models_section(self) -> None:
        with FakeHome() as home:
            p = home / ".grok"
            p.mkdir()
            (p / "config.toml").write_text(
                '[api]\nkey = "abc"\n\n[models]\ndefault = "grok-4.5"\nfast = "grok-3-mini"\n'
            )
            res = agent._write_grok_cli_model("grok-3-mini")
            self.assertTrue(res["ok"] and res["changed"], res)
            text = (p / "config.toml").read_text()
            self.assertIn('default = "grok-3-mini"', text)
            self.assertIn('key = "abc"', text)
            self.assertIn('fast = "grok-3-mini"', text)
            self.assertEqual(agent._read_grok_config_default(), "grok-3-mini")

    def test_appends_models_section_when_missing(self) -> None:
        with FakeHome() as home:
            p = home / ".grok"
            p.mkdir()
            (p / "config.toml").write_text('[api]\nkey = "abc"\n')
            res = agent._write_grok_cli_model("grok-4.5")
            self.assertTrue(res["ok"], res)
            self.assertEqual(agent._read_grok_config_default(), "grok-4.5")

    def test_creates_config_when_absent(self) -> None:
        with FakeHome():
            res = agent._write_grok_cli_model("grok-4.5")
            self.assertTrue(res["ok"], res)
            self.assertEqual(agent._read_grok_config_default(), "grok-4.5")


class SyncSettingsTests(unittest.TestCase):
    def test_disabled_via_env(self) -> None:
        with mock.patch.dict(os.environ, {"CF_SETTINGS_SYNC_CLI": "0"}):
            out = agent.sync_settings_to_cli({"claude": {"model": "haiku"}})
        self.assertFalse(out["enabled"])
        self.assertEqual(out["actions"], [])

    def test_syncs_both_drivers_and_updates_cache(self) -> None:
        with FakeHome(), mock.patch.dict(os.environ, {"CF_SETTINGS_SYNC_CLI": "1"}):
            agent.clear_settings_catalog_cache()
            # Seed a warm cache to verify in-place current update.
            agent._catalog_cache = {
                "claude": {
                    "currentModel": "fable",
                    "defaultModel": "fable",
                    "models": [
                        {"value": "fable", "label": "fable (current)", "default": True},
                        {"value": "haiku", "label": "haiku"},
                    ],
                },
                "grok": {"currentModel": "grok-4.5", "models": []},
            }
            agent._catalog_cache_fetched_at = time.time()
            out = agent.sync_settings_to_cli(
                {"claude": {"model": "haiku"}, "grok": {"model": "grok-4.5"}}
            )
            self.assertTrue(out["enabled"])
            self.assertEqual(len(out["actions"]), 2)
            self.assertTrue(all(a["ok"] for a in out["actions"]), out)
            cat = agent.get_settings_catalog()
            self.assertEqual(cat["claude"]["currentModel"], "haiku")
            labels = {o["value"]: o["label"] for o in cat["claude"]["models"]}
            self.assertEqual(labels["haiku"], "haiku (current)")
            self.assertEqual(labels["fable"], "fable")
            agent.clear_settings_catalog_cache()

    def test_bootstrap_sonnet_not_written_back(self) -> None:
        with FakeHome() as home, mock.patch.dict(os.environ, {"CF_SETTINGS_SYNC_CLI": "1"}):
            out = agent.sync_settings_to_cli({"claude": {"model": "sonnet"}})
            self.assertTrue(out["enabled"])
            claude_actions = [a for a in out["actions"] if a["driver"] == "claude"]
            self.assertEqual(claude_actions, [])
            self.assertFalse((home / ".claude" / "settings.json").exists())


class StaleWhileRevalidateTests(unittest.TestCase):
    def setUp(self) -> None:
        agent.clear_settings_catalog_cache()

    def tearDown(self) -> None:
        agent.clear_settings_catalog_cache()

    def test_expired_cache_served_stale_then_revalidated(self) -> None:
        calls = {"n": 0}

        def fake(*args, **kwargs) -> dict:
            calls["n"] += 1
            return {"fetchedAt": time.time(), "grok": {}, "claude": {}}

        with mock.patch.object(agent, "discover_settings_catalog", side_effect=fake):
            agent.get_settings_catalog()  # prime
            self.assertEqual(calls["n"], 1)
            # Expire the cache.
            agent._catalog_cache_fetched_at = time.time() - agent.CATALOG_TTL_SECONDS - 1
            out = agent.get_settings_catalog()
            self.assertEqual(out["cache"], "memory-stale-revalidating")
            # Background refresh lands shortly.
            deadline = time.time() + 3
            while calls["n"] < 2 and time.time() < deadline:
                time.sleep(0.02)
            self.assertEqual(calls["n"], 2, "background revalidation must run")
            out2 = agent.get_settings_catalog()
            self.assertEqual(out2["cache"], "memory")


if __name__ == "__main__":
    unittest.main()


class HelpCacheAndFileFirstTests(unittest.TestCase):
    """File-first discovery: steady-state polls spawn zero processes."""

    def setUp(self) -> None:
        agent.clear_settings_catalog_cache()
        agent.reset_cli_spawn_count()

    def tearDown(self) -> None:
        agent.clear_settings_catalog_cache()

    def test_get_cli_help_uses_disk_cache(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake_bin = Path(td) / "fakecli"
            fake_bin.write_text("#!/bin/sh\necho 'usage: fakecli [possible values: a, b]'\n")
            fake_bin.chmod(0o755)
            cache_file = Path(td) / "help_cache.json"
            with mock.patch.object(agent, "_HELP_CACHE_FILE", cache_file):
                r1 = agent.get_cli_help(str(fake_bin))
                self.assertFalse(r1["cached"])
                self.assertIn("possible values", r1["stdout"])
                spawns_after_first = agent.get_cli_spawn_count()
                r2 = agent.get_cli_help(str(fake_bin))
                self.assertTrue(r2["cached"])
                self.assertEqual(r2["stdout"].strip(), r1["stdout"].strip())
                self.assertEqual(agent.get_cli_spawn_count(), spawns_after_first,
                                 "cached help must not spawn")
                # Binary change invalidates the cache.
                fake_bin.write_text("#!/bin/sh\necho 'usage: fakecli v2'\n")
                fake_bin.chmod(0o755)
                r3 = agent.get_cli_help(str(fake_bin))
                self.assertFalse(r3["cached"])
                self.assertIn("v2", r3["stdout"])
                # refresh=True bypasses even a valid cache.
                r4 = agent.get_cli_help(str(fake_bin), refresh=True)
                self.assertFalse(r4["cached"])

    def test_shallow_claude_discovery_spawns_nothing_when_help_cached(self) -> None:
        with FakeHome() as home, tempfile.TemporaryDirectory() as td:
            (home / ".claude").mkdir()
            (home / ".claude" / "settings.json").write_text(json.dumps({"model": "haiku"}))
            fake_bin = Path(td) / "claude"
            fake_bin.write_text(
                "#!/bin/sh\necho \"use 'fable', 'haiku', or 'sonnet' "
                "--permission-mode <mode> [possible values: plan, acceptEdits]\"\n"
            )
            fake_bin.chmod(0o755)
            cache_file = Path(td) / "help_cache.json"
            with mock.patch.object(agent, "_HELP_CACHE_FILE", cache_file), \
                 mock.patch.object(agent, "CLAUDE_BIN", str(fake_bin)):
                agent.discover_claude_options(deep=False)  # warms help cache
                agent.reset_cli_spawn_count()
                out = agent.discover_claude_options(deep=False)
                self.assertEqual(agent.get_cli_spawn_count(), 0,
                                 "file-first discovery must not spawn")
                self.assertEqual(out["currentModel"], "haiku")
                values = [o["value"] for o in out["models"]]
                self.assertIn("haiku", values)
                self.assertIn("fable", values)
