"""Run instrumentation: recorder metric extraction, persistence, and the API.

Everything here is hermetic — no CLI is spawned, no credits are spent. Stream
events are fed straight into the recorder from fixtures shaped like real
Claude Code ``stream-json`` / Grok ``streaming-json`` output.
"""
import json

import pytest
from fastapi.testclient import TestClient

import main
import runs


@pytest.fixture(autouse=True)
def isolated_runs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(runs, "RUNS_DIR", tmp_path / "runs")
    runs.RUNS_DIR.mkdir()
    runs.reset_cache_for_tests()
    yield
    runs.reset_cache_for_tests()


@pytest.fixture
def client():
    return TestClient(main.app)


# --- Claude Code stream-json fixtures ----------------------------------------
CLAUDE_INIT = {
    "type": "system",
    "subtype": "init",
    "session_id": "sess-abc",
    "model": "claude-fable-5",
}
CLAUDE_ASSISTANT_TOOLS = {
    "type": "assistant",
    "session_id": "sess-abc",
    "message": {
        "content": [
            {"type": "text", "text": "Let me look around."},
            {"type": "tool_use", "name": "Read", "input": {}},
            {"type": "tool_use", "name": "Bash", "input": {}},
        ]
    },
}
CLAUDE_RESULT = {
    "type": "result",
    "subtype": "success",
    "session_id": "sess-abc",
    "num_turns": 7,
    "total_cost_usd": 0.1234,
    "duration_ms": 55000,
    "usage": {
        "input_tokens": 1200,
        "output_tokens": 3400,
        "cache_read_input_tokens": 50000,
        "cache_creation_input_tokens": 900,
    },
}


def test_recorder_extracts_claude_metrics():
    rec = runs.new_run(kind="build", topicId="t1", slug="hash-tables", title="Hash Tables")
    for evt in (CLAUDE_INIT, CLAUDE_ASSISTANT_TOOLS, CLAUDE_RESULT):
        rec.event(evt)
    final = rec.finish("success", exit_code=0)

    assert final["model"] == "claude-fable-5"
    assert final["sessionId"] == "sess-abc"
    assert final["tokensIn"] == 1200
    assert final["tokensOut"] == 3400
    assert final["cacheReadTokens"] == 50000
    assert final["cacheCreationTokens"] == 900
    assert final["totalTokens"] == 1200 + 3400 + 50000 + 900
    assert final["costUsd"] == pytest.approx(0.1234)
    assert final["turns"] == 7  # authoritative num_turns wins over observed
    assert final["toolCalls"] == 2
    assert final["status"] == "success"
    assert final["durationSeconds"] is not None


def test_recorder_extracts_grok_usage_and_retry():
    rec = runs.new_run(kind="plan", topicId="t2", slug="regex", title="Regex")
    rec.event({"type": "text", "data": "planning…", "sessionId": "grok-1"})
    # Cumulative usage snapshots within an attempt — last one wins.
    rec.event({"type": "end", "usage": {"prompt_tokens": 100, "completion_tokens": 40,
                                        "cost_in_usd_ticks": 500_000_000}})
    rec.retry()  # fold attempt 1, start attempt 2
    rec.event({"type": "end", "usage": {"prompt_tokens": 700, "completion_tokens": 300,
                                        "cost_in_usd_ticks": 1_500_000_000}})
    final = rec.finish("success")

    assert final["retries"] == 1
    assert final["attempts"] == 2
    assert final["tokensIn"] == 800
    assert final["tokensOut"] == 340
    assert final["costUsd"] == pytest.approx(2.0)  # 2e9 ticks = $2
    assert final["sessionId"] == "grok-1"


def test_run_persists_and_survives_index_reload():
    rec = runs.new_run(kind="build", topicId="t3", slug="tar", title="tar")
    rec.event(CLAUDE_RESULT)
    rec.line("hello from the log")
    rec.set_gate("lint", {"status": "pass", "detail": ""})
    rec.set_gate("validator", {"status": "pass", "passed": 12, "total": 12,
                               "passRate": 1.0, "levels": []})
    rec.finish("success")

    runs.reset_cache_for_tests()  # simulate server restart
    loaded = runs.get_run(rec.id)
    assert loaded is not None
    assert loaded["gates"]["lint"]["status"] == "pass"
    assert loaded["gates"]["validator"]["passRate"] == 1.0
    assert "hello from the log" in runs.run_log_text(rec.id)
    events = runs.run_events(rec.id)
    assert events["total"] == 1
    assert events["events"][0]["type"] == "result"


def test_orphaned_running_run_marked_error_on_reload():
    rec = runs.new_run(kind="build", topicId="t4", slug="x", title="X")
    # No finish() — simulates the server dying mid-run.
    rec.update()  # force a flush of the running state
    runs.reset_cache_for_tests()
    loaded = runs.get_run(rec.id)
    assert loaded["status"] == "error"
    assert "orphaned" in loaded["error"]


def test_metrics_summary_aggregates():
    a = runs.new_run(kind="build", topicId="t1", slug="a", title="A")
    a.event(CLAUDE_RESULT)
    a.set_gate("lint", {"status": "pass", "detail": ""})
    a.set_gate("build", {"status": "pass", "detail": ""})
    a.set_gate("validator", {"status": "fail", "passed": 6, "total": 12,
                             "passRate": 0.5, "levels": []})
    a.finish("success")
    b = runs.new_run(kind="plan", topicId="t2", slug="b", title="B")
    b.finish("error", error="boom")

    m = runs.metrics_summary()
    assert m["totalRuns"] == 2
    assert m["succeeded"] == 1
    assert m["failed"] == 1
    assert m["successRate"] == 0.5
    assert m["totalCostUsd"] == pytest.approx(0.1234)
    assert m["gates"]["lint"]["pass"] == 1
    assert m["gates"]["validator"]["fail"] == 1
    assert m["avgValidatorPassRate"] == 0.5


def test_runs_api_list_get_events_log_export(client):
    rec = runs.new_run(kind="improve", topicId="topic-9", slug="cron", title="Cron")
    rec.event(CLAUDE_INIT)
    rec.event(CLAUDE_RESULT)
    rec.line("improving…")
    rec.finish("success")

    listed = client.get("/api/runs").json()["runs"]
    assert [r["id"] for r in listed] == [rec.id]
    assert listed[0]["kind"] == "improve"

    # Filters
    assert client.get("/api/runs?kind=plan").json()["runs"] == []
    assert len(client.get("/api/runs?topicId=topic-9").json()["runs"]) == 1

    detail = client.get(f"/api/runs/{rec.id}").json()
    assert detail["costUsd"] == pytest.approx(0.1234)

    events = client.get(f"/api/runs/{rec.id}/events").json()
    assert events["total"] == 2

    log = client.get(f"/api/runs/{rec.id}/log").json()
    assert any("improving…" in line for line in log["lines"])

    # Exports (json bundle / raw ndjson / txt log) download as attachments.
    for fmt, needle in (("json", b'"run"'), ("ndjson", b'"result"'), ("txt", b"improving")):
        res = client.get(f"/api/runs/{rec.id}/export?format={fmt}")
        assert res.status_code == 200
        assert "attachment" in res.headers["content-disposition"]
        assert needle in res.content

    assert client.get("/api/runs/nope").status_code == 404
    assert client.get(f"/api/runs/{rec.id}/export?format=exe").status_code == 400

    metrics = client.get("/api/runs/metrics").json()
    assert metrics["totalRuns"] == 1


def test_validator_gate_on_template(tmp_path):
    """Auto-play the house template's example levels end-to-end (needs node)."""
    import shutil as _shutil
    import agent

    if not _shutil.which("node"):
        pytest.skip("node not available")
    template = agent.TEMPLATE_DIR
    if not template.exists():
        pytest.skip("template missing")
    dest = tmp_path / "concept"
    dest.mkdir()
    for item in ("src", "package.json", "tsconfig.json"):
        srcp = template / item
        if srcp.is_dir():
            _shutil.copytree(srcp, dest / item)
        elif srcp.is_file():
            _shutil.copy2(srcp, dest / item)
    # esbuild comes from the concept's node_modules; borrow the frontend's if
    # present so the test doesn't npm install.
    frontend_esbuild = template.parents[1] / "frontend" / "node_modules" / "esbuild"
    fe_root = agent.TEMPLATE_DIR.parents[1] / "frontend" / "node_modules"
    nm = dest / "node_modules"
    nm.mkdir()
    if frontend_esbuild.exists():
        _shutil.copytree(frontend_esbuild, nm / "esbuild")
        for helper in fe_root.glob("@esbuild*"):
            _shutil.copytree(helper, nm / helper.name)
    lines = []
    result = agent.run_validator_gate(dest, lines.append)
    if result.get("status") == "skipped":
        pytest.skip(f"validator skipped: {result.get('detail')}")
    assert result["status"] == "pass"
    assert result["passed"] == result["total"] == 2
    assert result["passRate"] == 1.0


def test_gates_helper_marks_skipped_on_build_failure(tmp_path):
    class FakeRecorder:
        def __init__(self):
            self.gates = {}

        def set_gate(self, name, result):
            self.gates[name] = result

    fake = FakeRecorder()
    main._run_verification_gates(fake, tmp_path, lambda _l: None, build_ok=False)
    assert fake.gates["build"]["status"] == "fail"
    assert fake.gates["lint"]["status"] == "skipped"
    assert fake.gates["validator"]["status"] == "skipped"
