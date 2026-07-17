"""Unit tests for agent driver settings + command dispatch.

Exercises the shipped ``agent`` module (settings persistence, argv builders,
``run_agent`` routing) and FastAPI ``/api/settings`` via TestClient.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Ensure backend/ is importable when run as ``python test_driver_settings.py``.
BACKEND = Path(__file__).resolve().parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import agent  # noqa: E402
from main import app  # noqa: E402

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None  # type: ignore


class SettingsPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.settings_path = Path(self._tmp.name) / "settings.json"
        self._orig = agent.SETTINGS_FILE
        agent.SETTINGS_FILE = self.settings_path

    def tearDown(self) -> None:
        agent.SETTINGS_FILE = self._orig
        self._tmp.cleanup()

    def test_default_is_grok(self) -> None:
        s = agent.load_settings()
        self.assertEqual(s["driver"], "grok")
        self.assertIn("model", s["grok"])
        self.assertIn("model", s["claude"])

    def test_save_and_reload_roundtrip(self) -> None:
        saved = agent.save_settings(
            {
                "driver": "claude",
                "claude": {
                    "model": "haiku",
                    "effort": "low",
                    "dangerouslySkipPermissions": True,
                },
                "grok": {"model": "grok-3-mini", "reasoningEffort": "high"},
            }
        )
        self.assertEqual(saved["driver"], "claude")
        self.assertEqual(saved["claude"]["model"], "haiku")
        self.assertEqual(saved["claude"]["effort"], "low")
        self.assertEqual(saved["grok"]["model"], "grok-3-mini")

        reloaded = agent.load_settings()
        self.assertEqual(reloaded["driver"], "claude")
        self.assertEqual(reloaded["claude"]["model"], "haiku")
        self.assertEqual(reloaded["grok"]["model"], "grok-3-mini")
        self.assertTrue(self.settings_path.is_file())
        disk = json.loads(self.settings_path.read_text())
        self.assertEqual(disk["driver"], "claude")

    def test_alias_normalization(self) -> None:
        s = agent.normalize_settings({"driver": "claude code"})
        self.assertEqual(s["driver"], "claude")
        s2 = agent.normalize_settings({"driver": "Grok Build"})
        self.assertEqual(s2["driver"], "grok")


class DriverDispatchTests(unittest.TestCase):
    def test_grok_cmd_includes_model_and_streaming(self) -> None:
        cwd = Path("/tmp/fake-topic")
        cmd = agent.build_driver_cmd(
            "grok",
            "plan this",
            cwd,
            settings={
                "driver": "grok",
                "grok": {
                    "model": "grok-3-mini",
                    "permissionMode": "bypassPermissions",
                    "reasoningEffort": "high",
                },
            },
            dangerously_skip=True,
        )
        self.assertEqual(cmd[0], agent.GROK_BIN)
        self.assertIn("-p", cmd)
        self.assertIn("plan this", cmd)
        self.assertIn("--output-format", cmd)
        self.assertIn("streaming-json", cmd)
        self.assertIn("--always-approve", cmd)
        self.assertIn("--cwd", cmd)
        self.assertIn(str(cwd), cmd)
        self.assertIn("--model", cmd)
        self.assertIn("grok-3-mini", cmd)
        self.assertIn("--reasoning-effort", cmd)
        self.assertIn("high", cmd)
        self.assertIn("--permission-mode", cmd)
        self.assertIn("bypassPermissions", cmd)

    def test_claude_cmd_includes_model_and_stream_json(self) -> None:
        cwd = Path("/tmp/fake-topic")
        cmd = agent.build_driver_cmd(
            "claude",
            "build this",
            cwd,
            settings={
                "driver": "claude",
                "claude": {
                    "model": "haiku",
                    "permissionMode": "acceptEdits",
                    "effort": "medium",
                    "dangerouslySkipPermissions": True,
                },
            },
            dangerously_skip=True,
        )
        self.assertEqual(cmd[0], agent.CLAUDE_BIN)
        self.assertIn("-p", cmd)
        self.assertIn("build this", cmd)
        self.assertIn("--output-format", cmd)
        self.assertIn("stream-json", cmd)
        self.assertIn("--verbose", cmd)
        self.assertIn("--model", cmd)
        self.assertIn("haiku", cmd)
        self.assertIn("--effort", cmd)
        self.assertIn("medium", cmd)
        self.assertIn("--dangerously-skip-permissions", cmd)

    def test_run_agent_routes_to_grok(self) -> None:
        lines: list = []
        with mock.patch.object(agent, "run_grok", return_value={"sessionId": "g1", "error": None}) as rg, \
             mock.patch.object(agent, "run_claude") as rc:
            result = agent.run_agent(
                "hi",
                Path("."),
                on_line=lines.append,
                settings={"driver": "grok", "grok": {"model": "grok-4"}},
            )
        self.assertEqual(result["sessionId"], "g1")
        rg.assert_called_once()
        rc.assert_not_called()
        self.assertTrue(any("Grok Build" in ln for ln in lines))

    def test_run_agent_routes_to_claude(self) -> None:
        lines: list = []
        with mock.patch.object(agent, "run_claude", return_value={"sessionId": "c1", "error": None}) as rc, \
             mock.patch.object(agent, "run_grok") as rg:
            result = agent.run_agent(
                "hi",
                Path("."),
                on_line=lines.append,
                settings={
                    "driver": "claude",
                    "claude": {
                        "model": "sonnet",
                        "dangerouslySkipPermissions": True,
                    },
                },
            )
        self.assertEqual(result["sessionId"], "c1")
        rc.assert_called_once()
        rg.assert_not_called()
        self.assertTrue(any("Claude Code" in ln for ln in lines))

    def test_jobs_use_run_agent_not_run_grok(self) -> None:
        """Static check: main.py agent jobs call run_agent, not run_grok."""
        main_src = (BACKEND / "main.py").read_text()
        self.assertIn("agent.run_agent(", main_src)
        # Jobs must not hard-code run_grok anymore.
        for needle in (
            "agent.run_grok(prompt",
            "agent.run_grok(\n",
            "agent.run_grok(agent.",
        ):
            self.assertNotIn(needle, main_src)
        # Count run_agent call sites (plan, consolidate, build, improve).
        self.assertGreaterEqual(main_src.count("agent.run_agent("), 4)


@unittest.skipIf(TestClient is None, "fastapi TestClient unavailable")
class SettingsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.settings_path = Path(self._tmp.name) / "settings.json"
        self._orig = agent.SETTINGS_FILE
        agent.SETTINGS_FILE = self.settings_path
        # Reset to defaults for a clean API surface.
        agent.save_settings(agent.default_settings())
        self.client = TestClient(app)

    def tearDown(self) -> None:
        agent.SETTINGS_FILE = self._orig
        self._tmp.cleanup()

    def test_get_put_settings_roundtrip(self) -> None:
        r = self.client.get("/api/settings")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["driver"], "grok")

        r2 = self.client.put(
            "/api/settings",
            json={
                "driver": "claude",
                "claude": {"model": "haiku", "effort": "low"},
            },
        )
        self.assertEqual(r2.status_code, 200)
        saved = r2.json()
        self.assertEqual(saved["driver"], "claude")
        self.assertEqual(saved["claude"]["model"], "haiku")
        self.assertEqual(saved["claude"]["effort"], "low")

        r3 = self.client.get("/api/settings")
        self.assertEqual(r3.json()["driver"], "claude")
        self.assertEqual(r3.json()["claude"]["model"], "haiku")

        # Switch back to grok with a distinct model.
        r4 = self.client.put(
            "/api/settings",
            json={
                "driver": "grok",
                "grok": {"model": "grok-3-mini", "reasoningEffort": "medium"},
            },
        )
        self.assertEqual(r4.status_code, 200)
        self.assertEqual(r4.json()["driver"], "grok")
        self.assertEqual(r4.json()["grok"]["model"], "grok-3-mini")
        self.assertEqual(r4.json()["grok"]["reasoningEffort"], "medium")


class StreamCoalescerTests(unittest.TestCase):
    def test_claude_assistant_text_emits_lines(self) -> None:
        lines: list = []
        c = agent._StreamCoalescer(lines.append, driver_label="Claude")
        c.push(
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "text", "text": "hello world\nnext"}],
                },
            }
        )
        c.push({"type": "result", "subtype": "success", "is_error": False})
        self.assertTrue(any("hello world" in ln for ln in lines))
        self.assertTrue(any("finished" in ln for ln in lines))


if __name__ == "__main__":
    unittest.main(verbosity=2)
