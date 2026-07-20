"""Unit tests for agent driver settings + command dispatch.

Exercises the shipped ``agent`` module (settings persistence, argv builders,
``run_agent`` routing) and FastAPI ``/api/settings`` via TestClient.

Grok Build is the only factory driver; Claude Code is deprecated.
"""
from __future__ import annotations

import json
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
        self.assertNotIn("claude", s)
        self.assertIn("maxBuildBudgetUsd", s["grok"])
        self.assertEqual(s["grok"]["maxBuildBudgetUsd"], "")

    def test_save_and_reload_roundtrip(self) -> None:
        saved = agent.save_settings(
            {
                "driver": "grok",
                "grok": {"model": "grok-3-mini", "reasoningEffort": "high"},
            }
        )
        self.assertEqual(saved["driver"], "grok")
        self.assertEqual(saved["grok"]["model"], "grok-3-mini")
        self.assertNotIn("claude", saved)

        reloaded = agent.load_settings()
        self.assertEqual(reloaded["driver"], "grok")
        self.assertEqual(reloaded["grok"]["model"], "grok-3-mini")
        self.assertTrue(self.settings_path.is_file())
        disk = json.loads(self.settings_path.read_text())
        self.assertEqual(disk["driver"], "grok")
        self.assertNotIn("claude", disk)

    def test_stale_claude_driver_coerces_to_grok(self) -> None:
        """Any residual Claude driver/alias becomes grok; claude section dropped."""
        for raw_driver in (
            "claude",
            "Claude Code",
            "claude code",
            "anthropic",
            "CLAUDE",
        ):
            s = agent.normalize_settings(
                {
                    "driver": raw_driver,
                    "claude": {"model": "haiku", "effort": "low"},
                    "grok": {"model": "grok-4.5"},
                }
            )
            self.assertEqual(s["driver"], "grok", msg=repr(raw_driver))
            self.assertNotIn("claude", s)
            self.assertEqual(s["grok"]["model"], "grok-4.5")

        # Persist coerce on save/load
        saved = agent.save_settings(
            {
                "driver": "claude",
                "claude": {"model": "sonnet"},
                "grok": {"model": "grok-3-mini"},
            }
        )
        self.assertEqual(saved["driver"], "grok")
        self.assertNotIn("claude", saved)
        reloaded = agent.load_settings()
        self.assertEqual(reloaded["driver"], "grok")
        self.assertNotIn("claude", reloaded)
        disk = json.loads(self.settings_path.read_text())
        self.assertEqual(disk["driver"], "grok")
        self.assertNotIn("claude", disk)

    def test_alias_normalization(self) -> None:
        s = agent.normalize_settings({"driver": "claude code"})
        self.assertEqual(s["driver"], "grok")
        s2 = agent.normalize_settings({"driver": "Grok Build"})
        self.assertEqual(s2["driver"], "grok")

    def test_max_build_budget_usd_roundtrip(self) -> None:
        """Dollar budget persists via the same normalize/save/load path as UI."""
        saved = agent.save_settings(
            {
                "driver": "grok",
                "grok": {"maxBuildBudgetUsd": 5},
            }
        )
        self.assertEqual(saved["grok"]["maxBuildBudgetUsd"], "5")
        reloaded = agent.load_settings()
        self.assertEqual(reloaded["grok"]["maxBuildBudgetUsd"], "5")
        disk = json.loads(self.settings_path.read_text())
        self.assertEqual(disk["grok"]["maxBuildBudgetUsd"], "5")

        # Clear → unlimited
        cleared = agent.save_settings(
            {"driver": "grok", "grok": {"maxBuildBudgetUsd": ""}}
        )
        self.assertEqual(cleared["grok"]["maxBuildBudgetUsd"], "")
        self.assertIsNone(
            agent.dollars_to_budget_tokens(cleared["grok"]["maxBuildBudgetUsd"])
        )

        # null also clears
        nulled = agent.save_settings(
            {"driver": "grok", "grok": {"maxBuildBudgetUsd": None}}
        )
        self.assertEqual(nulled["grok"]["maxBuildBudgetUsd"], "")


class BudgetConversionTests(unittest.TestCase):
    """Shipped dollars→tokens helper (no re-implementation in the test)."""

    def test_positive_dollars_yield_positive_int_tokens(self) -> None:
        for usd in (1, 1.0, "1", "$1", 0.5, "0.50", 2.25):
            tokens = agent.dollars_to_budget_tokens(usd)
            self.assertIsInstance(tokens, int, msg=repr(usd))
            self.assertGreater(tokens, 0, msg=repr(usd))

        # Monotonic: more dollars → more tokens
        self.assertGreater(
            agent.dollars_to_budget_tokens(2), agent.dollars_to_budget_tokens(1)
        )
        # Half dollar is half of one dollar (rate is linear)
        one = agent.dollars_to_budget_tokens(1)
        half = agent.dollars_to_budget_tokens(0.5)
        self.assertEqual(half, one // 2)
        # Rate constant is exposed and used
        self.assertEqual(
            agent.dollars_to_budget_tokens(1), agent.TOKENS_PER_USD
        )

    def test_unlimited_inputs_yield_none(self) -> None:
        for val in (None, "", "  ", 0, 0.0, "0", -1, "-5", "abc", float("nan")):
            self.assertIsNone(
                agent.dollars_to_budget_tokens(val), msg=repr(val)
            )
            self.assertIsNone(agent.parse_budget_usd(val), msg=repr(val))

    def test_resolve_prefers_override_then_settings(self) -> None:
        cfg = agent.normalize_settings(
            {"driver": "grok", "grok": {"maxBuildBudgetUsd": "3"}}
        )
        # Override wins
        self.assertEqual(
            agent.resolve_build_budget_tokens(override=1, settings=cfg),
            agent.dollars_to_budget_tokens(1),
        )
        # Explicit unlimited override beats settings default
        self.assertIsNone(
            agent.resolve_build_budget_tokens(override=None, settings=cfg)
        )
        self.assertIsNone(
            agent.resolve_build_budget_tokens(override="", settings=cfg)
        )
        # Unset override → settings
        self.assertEqual(
            agent.resolve_build_budget_tokens(settings=cfg),
            agent.dollars_to_budget_tokens(3),
        )


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
        # Non-build path: no goal budget wrapping
        p_idx = cmd.index("-p")
        self.assertNotIn("--budget", cmd[p_idx + 1])
        self.assertFalse(cmd[p_idx + 1].startswith("/goal"))

    def test_claude_looking_settings_still_build_grok_argv(self) -> None:
        """Residual claude driver blobs must not produce Claude bin argv."""
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
                "grok": {"model": "grok-4.5", "permissionMode": "bypassPermissions"},
            },
            dangerously_skip=True,
        )
        self.assertEqual(cmd[0], agent.GROK_BIN)
        self.assertNotEqual(cmd[0], agent.CLAUDE_BIN)
        self.assertIn("streaming-json", cmd)
        self.assertNotIn("stream-json", cmd)
        self.assertIn("--always-approve", cmd)
        self.assertNotIn("--dangerously-skip-permissions", cmd)
        self.assertIn("grok-4.5", cmd)
        self.assertNotIn("haiku", cmd)

    def test_grok_build_cmd_includes_budget_from_dollars(self) -> None:
        """Drive real build_grok_cmd / build_driver_cmd with a dollar budget."""
        cwd = Path("/tmp/fake-topic")
        usd = 1.0
        tokens = agent.dollars_to_budget_tokens(usd)
        self.assertIsNotNone(tokens)
        assert tokens is not None

        cmd = agent.build_grok_cmd(
            "build the app from PLAN.md",
            cwd,
            budget_tokens=tokens,
        )
        self.assertEqual(cmd[0], agent.GROK_BIN)
        self.assertIn("-p", cmd)
        prompt = cmd[cmd.index("-p") + 1]
        self.assertTrue(prompt.startswith("/goal "), prompt)
        self.assertIn("--budget", prompt)
        # Token value must equal the conversion helper (not a hard-coded argv)
        self.assertIn(str(tokens), prompt)
        self.assertIn("build the app from PLAN.md", prompt)

        # Via build_driver_cmd with build_budget_usd override
        cmd2 = agent.build_driver_cmd(
            "grok",
            "build the app from PLAN.md",
            cwd,
            settings={"driver": "grok", "grok": {"maxBuildBudgetUsd": ""}},
            build_budget_usd=usd,
        )
        prompt2 = cmd2[cmd2.index("-p") + 1]
        self.assertIn("--budget", prompt2)
        self.assertIn(str(tokens), prompt2)

        # Settings default when override unset but budget_tokens passed via resolve
        cmd3 = agent.build_driver_cmd(
            "grok",
            "build the app from PLAN.md",
            cwd,
            settings={"driver": "grok", "grok": {"maxBuildBudgetUsd": "0.5"}},
            budget_tokens=agent.resolve_build_budget_tokens(
                settings={"driver": "grok", "grok": {"maxBuildBudgetUsd": "0.5"}}
            ),
        )
        half = agent.dollars_to_budget_tokens(0.5)
        prompt3 = cmd3[cmd3.index("-p") + 1]
        self.assertIn(str(half), prompt3)
        self.assertIn("--budget", prompt3)

    def test_grok_build_cmd_omits_budget_when_unlimited(self) -> None:
        cwd = Path("/tmp/fake-topic")
        for tokens in (None, 0, -1):
            cmd = agent.build_grok_cmd(
                "build the app",
                cwd,
                budget_tokens=tokens,  # type: ignore[arg-type]
            )
            prompt = cmd[cmd.index("-p") + 1]
            self.assertEqual(prompt, "build the app")
            self.assertNotIn("--budget", prompt)
            self.assertFalse(prompt.startswith("/goal"))

        cmd2 = agent.build_driver_cmd(
            "grok",
            "build the app",
            cwd,
            settings={"driver": "grok", "grok": {"maxBuildBudgetUsd": ""}},
            build_budget_usd=None,  # explicit unlimited
        )
        prompt2 = cmd2[cmd2.index("-p") + 1]
        self.assertNotIn("--budget", prompt2)

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

    def test_run_agent_build_budget_passed_to_grok(self) -> None:
        lines: list = []
        settings = {
            "driver": "grok",
            "grok": {"model": "grok-4", "maxBuildBudgetUsd": "1"},
        }
        expected = agent.dollars_to_budget_tokens(1)
        with mock.patch.object(
            agent, "run_grok", return_value={"sessionId": "g1", "error": None}
        ) as rg:
            agent.run_agent(
                "build it",
                Path("."),
                on_line=lines.append,
                settings=settings,
                apply_build_budget=True,
            )
        self.assertEqual(rg.call_args.kwargs["budget_tokens"], expected)
        self.assertTrue(any("Build budget" in ln and "tokens" in ln for ln in lines))

        # Explicit unlimited override
        lines.clear()
        with mock.patch.object(
            agent, "run_grok", return_value={"sessionId": "g1", "error": None}
        ) as rg:
            agent.run_agent(
                "build it",
                Path("."),
                on_line=lines.append,
                settings=settings,
                apply_build_budget=True,
                build_budget_usd=None,
            )
        self.assertIsNone(rg.call_args.kwargs["budget_tokens"])
        self.assertTrue(any("unlimited" in ln.lower() for ln in lines))

    def test_run_agent_ignores_stale_claude_settings(self) -> None:
        """Stale driver:claude must still call run_grok, never run_claude."""
        lines: list = []
        with mock.patch.object(
            agent, "run_grok", return_value={"sessionId": "g1", "error": None}
        ) as rg, mock.patch.object(agent, "run_claude") as rc:
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
                    "grok": {"model": "grok-4.5"},
                },
            )
        self.assertEqual(result["sessionId"], "g1")
        rg.assert_called_once()
        rc.assert_not_called()
        self.assertTrue(any("Grok Build" in ln for ln in lines))
        self.assertFalse(any("Claude Code" in ln for ln in lines))
        # Grok model from settings is what was passed through
        self.assertEqual(rg.call_args.kwargs.get("model") or rg.call_args[1].get("model"), "grok-4.5")

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
        self.assertNotIn("claude", body)

        # Attempting to select Claude is coerced to Grok-only settings.
        r2 = self.client.put(
            "/api/settings",
            json={
                "driver": "claude",
                "claude": {"model": "haiku", "effort": "low"},
                "grok": {"model": "grok-3-mini"},
            },
        )
        self.assertEqual(r2.status_code, 200)
        saved = r2.json()
        self.assertEqual(saved["driver"], "grok")
        self.assertNotIn("claude", saved)
        self.assertEqual(saved["grok"]["model"], "grok-3-mini")

        r3 = self.client.get("/api/settings")
        self.assertEqual(r3.json()["driver"], "grok")
        self.assertNotIn("claude", r3.json())

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

    def test_build_budget_settings_api_roundtrip(self) -> None:
        r = self.client.put(
            "/api/settings",
            json={
                "driver": "grok",
                "grok": {"maxBuildBudgetUsd": 2.5},
            },
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["grok"]["maxBuildBudgetUsd"], "2.5")

        r2 = self.client.get("/api/settings")
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["grok"]["maxBuildBudgetUsd"], "2.5")
        # Same value the conversion helper would use
        self.assertEqual(
            agent.dollars_to_budget_tokens(r2.json()["grok"]["maxBuildBudgetUsd"]),
            agent.dollars_to_budget_tokens(2.5),
        )

        # Clear to unlimited
        r3 = self.client.put(
            "/api/settings",
            json={"driver": "grok", "grok": {"maxBuildBudgetUsd": ""}},
        )
        self.assertEqual(r3.status_code, 200)
        self.assertEqual(r3.json()["grok"]["maxBuildBudgetUsd"], "")
        self.assertIsNone(
            agent.dollars_to_budget_tokens(r3.json()["grok"]["maxBuildBudgetUsd"])
        )


class StreamCoalescerTests(unittest.TestCase):
    def test_assistant_text_emits_lines(self) -> None:
        lines: list = []
        c = agent._StreamCoalescer(lines.append, driver_label="Grok")
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


class BudgetUxStaticTests(unittest.TestCase):
    """Structural check: PlanModal / SettingsModal expose dollar budget UX."""

    ROOT = BACKEND.parent

    def test_plan_modal_budget_near_approve_build(self) -> None:
        src = (self.ROOT / "frontend/src/components/PlanModal.tsx").read_text()
        self.assertIn("Approve & build", src)
        self.assertIn("budgetUsd", src)
        self.assertNotIn("showGrokBudget", src)
        # Budget control sits in the same footer as the build action.
        footer_idx = src.rfind("Approve & build")
        # Label copy next to the $ input (not the earlier code comment).
        budget_idx = src.rfind("· empty = unlimited")
        self.assertGreater(footer_idx, 0)
        self.assertGreater(budget_idx, 0)
        self.assertLess(abs(footer_idx - budget_idx), 2000)
        self.assertIn('placeholder="Unlimited"', src)

    def test_settings_modal_grok_max_build_budget(self) -> None:
        src = (self.ROOT / "frontend/src/components/SettingsModal.tsx").read_text()
        self.assertIn("Max build budget", src)
        self.assertIn("maxBuildBudgetUsd", src)
        self.assertIn("empty = unlimited", src)

    def test_main_build_job_threads_budget(self) -> None:
        src = (BACKEND / "main.py").read_text()
        self.assertIn("apply_build_budget=True", src)
        self.assertIn("build_budget_usd", src)
        self.assertIn("budgetUsd", src)


class DeprecateClaudeUxStaticTests(unittest.TestCase):
    """Settings UI is Grok-only; types no longer advertise Claude as selectable."""

    ROOT = BACKEND.parent

    def test_settings_modal_no_claude_driver_toggle(self) -> None:
        src = (self.ROOT / "frontend/src/components/SettingsModal.tsx").read_text()
        self.assertIn("Grok Build", src)
        self.assertIn("Grok Build options", src)
        self.assertNotIn("Claude Code", src)
        self.assertNotIn('setDriver("claude")', src)
        self.assertNotIn("patchClaude", src)
        self.assertNotIn("Claude Code options", src)
        self.assertNotIn("dangerouslySkipPermissions", src)

    def test_api_types_grok_only_driver(self) -> None:
        src = (self.ROOT / "frontend/src/api.ts").read_text()
        self.assertIn('export type AgentDriver = "grok"', src)
        self.assertNotIn('"claude"', src.split("export type AgentDriver")[1].split(";")[0])
        self.assertNotIn("ClaudeDriverSettings", src)
        # FactorySettings should not require a claude section
        fs = src[src.find("export interface FactorySettings") : src.find("export interface FactorySettings") + 400]
        self.assertIn("grok:", fs)
        self.assertNotIn("claude:", fs)

    def test_plan_modal_no_claude_branch(self) -> None:
        src = (self.ROOT / "frontend/src/components/PlanModal.tsx").read_text()
        self.assertNotIn('driver === "claude"', src)
        self.assertNotIn('setDriver', src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
