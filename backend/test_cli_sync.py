"""Tests for widget → CLI write-back and stale-while-revalidate catalog.

Claude Code is deprecated as a factory driver: sync is Grok-only.
"""
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
    """``_write_claude_cli_model`` is a deprecated no-op (factory is Grok-only)."""

    def test_is_noop_skipped(self) -> None:
        with FakeHome() as home:
            res = agent._write_claude_cli_model("haiku")
            self.assertTrue(res["ok"], res)
            self.assertFalse(res["changed"])
            self.assertEqual(res.get("skipped"), "claude-deprecated")
            self.assertFalse((home / ".claude" / "settings.json").exists())

    def test_does_not_touch_existing_claude_settings(self) -> None:
        with FakeHome() as home:
            p = home / ".claude"
            p.mkdir()
            original = json.dumps(
                {"model": "fable", "theme": "dark", "permissions": {"allow": ["Bash"]}}
            )
            (p / "settings.json").write_text(original)
            res = agent._write_claude_cli_model("haiku")
            self.assertTrue(res["ok"])
            self.assertFalse(res["changed"])
            self.assertEqual((p / "settings.json").read_text(), original)


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
            out = agent.sync_settings_to_cli({"grok": {"model": "grok-4.5"}})
        self.assertFalse(out["enabled"])
        self.assertEqual(out["actions"], [])

    def test_syncs_grok_only_and_updates_cache(self) -> None:
        with FakeHome(), mock.patch.dict(os.environ, {"CF_SETTINGS_SYNC_CLI": "1"}):
            agent.clear_settings_catalog_cache()
            # Seed a warm Grok-only cache to verify in-place current update.
            agent._catalog_cache = {
                "grok": {
                    "currentModel": "grok-4.5",
                    "defaultModel": "grok-4.5",
                    "models": [
                        {
                            "value": "grok-4.5",
                            "label": "grok-4.5 (current)",
                            "default": True,
                        },
                        {"value": "grok-3-mini", "label": "grok-3-mini"},
                    ],
                },
            }
            agent._catalog_cache_fetched_at = time.time()
            out = agent.sync_settings_to_cli(
                {
                    "driver": "claude",  # coerced away
                    "claude": {"model": "haiku"},
                    "grok": {"model": "grok-3-mini"},
                }
            )
            self.assertTrue(out["enabled"])
            self.assertEqual(len(out["actions"]), 1)
            self.assertEqual(out["actions"][0]["driver"], "grok")
            self.assertTrue(out["actions"][0]["ok"], out)
            # No Claude actions
            self.assertFalse(any(a.get("driver") == "claude" for a in out["actions"]))
            cat = agent.get_settings_catalog()
            self.assertEqual(cat["grok"]["currentModel"], "grok-3-mini")
            self.assertNotIn("claude", cat)
            labels = {o["value"]: o["label"] for o in cat["grok"]["models"]}
            self.assertEqual(labels["grok-3-mini"], "grok-3-mini (current)")
            self.assertEqual(labels["grok-4.5"], "grok-4.5")
            agent.clear_settings_catalog_cache()

    def test_claude_model_in_settings_is_ignored(self) -> None:
        """Claude section must not produce CLI write-back actions."""
        with FakeHome() as home, mock.patch.dict(os.environ, {"CF_SETTINGS_SYNC_CLI": "1"}):
            out = agent.sync_settings_to_cli(
                {"driver": "claude", "claude": {"model": "sonnet"}}
            )
            self.assertTrue(out["enabled"])
            claude_actions = [a for a in out["actions"] if a.get("driver") == "claude"]
            self.assertEqual(claude_actions, [])
            self.assertFalse((home / ".claude" / "settings.json").exists())

    def test_empty_grok_model_leaves_cli_alone(self) -> None:
        with FakeHome() as home, mock.patch.dict(os.environ, {"CF_SETTINGS_SYNC_CLI": "1"}):
            out = agent.sync_settings_to_cli({"grok": {"model": ""}})
            grok_actions = [a for a in out["actions"] if a.get("driver") == "grok"]
            self.assertEqual(grok_actions, [])
            self.assertFalse((home / ".grok" / "config.toml").exists())

    def test_override_detection_returns_empty(self) -> None:
        """Legacy helper always empty now that Claude is not a factory driver."""
        self.assertEqual(agent.detect_claude_model_overrides("sonnet"), [])


class ModelListCacheTests(unittest.TestCase):
    """Legacy Claude model-list cache helpers still work if called directly."""

    def test_deep_list_persists_and_shallow_reuses(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cache = Path(td) / "model_list.json"
            fake_bin = Path(td) / "claude"
            fake_bin.write_text("#!/bin/sh\necho hi\n")
            fake_bin.chmod(0o755)
            with mock.patch.object(agent, "_MODEL_LIST_CACHE_FILE", cache), \
                 mock.patch.object(agent, "CLAUDE_BIN", str(fake_bin)):
                agent.save_claude_model_list(["sonnet", "opus", "haiku", "fable"])
                got = agent.cached_claude_models()
                self.assertIn("haiku", got)
                self.assertEqual(set(got), {"sonnet", "opus", "haiku", "fable"})
                # Binary change invalidates the cache.
                fake_bin.write_text("#!/bin/sh\necho v2\n")
                fake_bin.chmod(0o755)
                self.assertEqual(agent.cached_claude_models(), [])


class CurrentModelReadTests(unittest.TestCase):
    """Cheap file-only current read + change signature (Grok only)."""

    def test_read_current_models_from_files(self) -> None:
        with FakeHome() as home:
            (home / ".claude").mkdir()
            (home / ".claude" / "settings.json").write_text(json.dumps({"model": "haiku"}))
            (home / ".grok").mkdir()
            (home / ".grok" / "config.toml").write_text('[models]\ndefault = "grok-4.5"\n')
            cur = agent.read_current_models()
            self.assertEqual(cur["grok"]["currentModel"], "grok-4.5")
            self.assertNotIn("claude", cur)

    def test_signature_changes_on_grok_edit(self) -> None:
        with FakeHome() as home:
            (home / ".grok").mkdir()
            f = home / ".grok" / "config.toml"
            f.write_text('[models]\ndefault = "grok-4.5"\n')
            sig1 = agent.current_models_signature()
            time.sleep(0.01)
            f.write_text('[models]\ndefault = "grok-3-mini"\n')
            os.utime(f, None)
            self.assertNotEqual(sig1, agent.current_models_signature())


class StaleWhileRevalidateTests(unittest.TestCase):
    def setUp(self) -> None:
        agent.clear_settings_catalog_cache()

    def tearDown(self) -> None:
        agent.clear_settings_catalog_cache()

    def test_expired_cache_served_stale_then_revalidated(self) -> None:
        calls = {"n": 0}

        def fake(*args, **kwargs) -> dict:
            calls["n"] += 1
            return {"fetchedAt": time.time(), "grok": {}}

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
        """Inert helper still works file-first if invoked directly."""
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

    def test_discover_settings_catalog_is_grok_only(self) -> None:
        """Shipped catalog path must not invoke Claude discovery."""
        with mock.patch.object(
            agent,
            "discover_grok_options",
            return_value={"models": [], "currentModel": "grok-4.5"},
        ) as dg, mock.patch.object(agent, "discover_claude_options") as dc:
            cat = agent.discover_settings_catalog(deep=False)
            dg.assert_called_once()
            dc.assert_not_called()
            self.assertIn("grok", cat)
            self.assertNotIn("claude", cat)
            self.assertEqual(cat["grok"]["currentModel"], "grok-4.5")


if __name__ == "__main__":
    unittest.main()
