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

    def test_explicit_sonnet_choice_is_written(self) -> None:
        """Regression: picking 'sonnet' in the widget must persist, not be
        dropped as a bootstrap sentinel (that heuristic is read-side only)."""
        with FakeHome() as home, mock.patch.dict(os.environ, {"CF_SETTINGS_SYNC_CLI": "1"}):
            out = agent.sync_settings_to_cli({"claude": {"model": "sonnet"}})
            self.assertTrue(out["enabled"])
            claude_actions = [a for a in out["actions"] if a["driver"] == "claude"]
            self.assertEqual(len(claude_actions), 1)
            self.assertTrue(claude_actions[0]["ok"])
            self.assertTrue(claude_actions[0].get("verified"))
            self.assertEqual(agent._read_claude_user_settings_model(), "sonnet")
            data = json.loads((home / ".claude" / "settings.json").read_text())
            self.assertEqual(data["model"], "sonnet")

    def test_empty_model_leaves_cli_alone(self) -> None:
        with FakeHome() as home, mock.patch.dict(os.environ, {"CF_SETTINGS_SYNC_CLI": "1"}):
            out = agent.sync_settings_to_cli({"claude": {"model": ""}})
            claude_actions = [a for a in out["actions"] if a["driver"] == "claude"]
            self.assertEqual(claude_actions, [])
            self.assertFalse((home / ".claude" / "settings.json").exists())

    def test_override_detection_env_and_project(self) -> None:
        with FakeHome() as home, mock.patch.object(Path, "cwd", return_value=home), \
             mock.patch.dict(os.environ, {"CF_SETTINGS_SYNC_CLI": "1", "ANTHROPIC_MODEL": "fable"}):
            (home / ".claude").mkdir(parents=True, exist_ok=True)
            (home / ".claude" / "settings.local.json").write_text(json.dumps({"model": "opus"}))
            out = agent.sync_settings_to_cli({"claude": {"model": "sonnet"}})
            a = [x for x in out["actions"] if x["driver"] == "claude"][0]
            sources = {o["source"] for o in a.get("overriddenBy", [])}
            self.assertIn("env:ANTHROPIC_MODEL", sources)
            self.assertIn("project:.claude/settings.local.json", sources)


class ModelListCacheTests(unittest.TestCase):
    """Fix 2: haiku (absent from --help) survives shallow polls via disk cache."""

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
    """Fix 3 backend: cheap file-only current read + change signature."""

    def test_read_current_models_from_files(self) -> None:
        with FakeHome() as home:
            (home / ".claude").mkdir()
            (home / ".claude" / "settings.json").write_text(json.dumps({"model": "haiku"}))
            (home / ".grok").mkdir()
            (home / ".grok" / "config.toml").write_text('[models]\ndefault = "grok-4.5"\n')
            cur = agent.read_current_models()
            self.assertEqual(cur["claude"]["currentModel"], "haiku")
            self.assertEqual(cur["grok"]["currentModel"], "grok-4.5")

    def test_signature_changes_on_edit(self) -> None:
        with FakeHome() as home:
            (home / ".claude").mkdir()
            f = home / ".claude" / "settings.json"
            f.write_text(json.dumps({"model": "sonnet"}))
            sig1 = agent.current_models_signature()
            time.sleep(0.01)
            f.write_text(json.dumps({"model": "haiku"}))
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
