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
    # Legacy path: cost_in_usd_ticks nested under usage (pre-event-level cost).
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


# Live Grok Build ``streaming-json`` end shape (from run_16f8001821bd):
# cost is top-level; usage has tokens only — no cost_in_usd_ticks.
GROK_END_LIVE = {
    "type": "end",
    "stopReason": "end_turn",
    "sessionId": "019f71da-bdb3-7123-9284-c0e5bcd69a28",
    "usage": {
        "input_tokens": 114343,
        "cache_read_input_tokens": 327040,
        "output_tokens": 28435,
        "reasoning_tokens": 1109,
        "total_tokens": 469818,
    },
    "num_turns": 12,
    "total_cost_usd": 0.56947,
    "total_cost_usd_ticks": 5_694_700_000,
}


def test_recorder_extracts_grok_end_event_level_cost():
    """Grok CLI reports cost on the end event, not inside usage — must not stay null."""
    rec = runs.new_run(
        kind="build",
        topicId="t-rl",
        slug="reinforcement-learning",
        title="Reinforcement Learning",
        driver="grok",
    )
    rec.event({"type": "text", "data": "building…", "sessionId": GROK_END_LIVE["sessionId"]})
    rec.event(GROK_END_LIVE)
    final = rec.finish("success", exit_code=0)

    assert final["costUsd"] == pytest.approx(0.56947)
    assert final["tokensIn"] == 114343
    assert final["tokensOut"] == 28435
    assert final["cacheReadTokens"] == 327040
    assert final["totalTokens"] == 114343 + 28435 + 327040
    assert final["turns"] == 12
    assert final["sessionId"] == GROK_END_LIVE["sessionId"]


def test_recorder_extracts_grok_end_cost_from_ticks_only():
    """When total_cost_usd is absent, scale total_cost_usd_ticks (1e9 ticks = $1)."""
    rec = runs.new_run(kind="build", topicId="t5", slug="ticks", title="Ticks")
    rec.event({
        "type": "end",
        "usage": {"input_tokens": 10, "output_tokens": 5},
        "total_cost_usd_ticks": 500_000_000,  # $0.50
    })
    final = rec.finish("success")
    assert final["costUsd"] == pytest.approx(0.5)
    assert final["tokensIn"] == 10
    assert final["tokensOut"] == 5


def test_recorder_does_not_double_count_event_and_usage_cost():
    """If end has total_cost_usd AND usage.cost_in_usd_ticks, count once."""
    rec = runs.new_run(kind="build", topicId="t6", slug="once", title="Once")
    rec.event({
        "type": "end",
        "total_cost_usd": 0.50,
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 40,
            "cost_in_usd_ticks": 500_000_000,  # same $0.50
        },
    })
    final = rec.finish("success")
    assert final["costUsd"] == pytest.approx(0.50)
    assert final["tokensIn"] == 100
    assert final["tokensOut"] == 40


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
    a = runs.new_run(
        kind="build", topicId="t1", slug="a", title="A", source=runs.SOURCE_APP
    )
    a.event(CLAUDE_RESULT)
    a.set_gate("lint", {"status": "pass", "detail": ""})
    a.set_gate("build", {"status": "pass", "detail": ""})
    a.set_gate("validator", {"status": "fail", "passed": 6, "total": 12,
                             "passRate": 0.5, "levels": []})
    a.finish("success")
    b = runs.new_run(
        kind="plan", topicId="t2", slug="b", title="B", source=runs.SOURCE_APP
    )
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
    rec = runs.new_run(
        kind="improve",
        topicId="topic-9",
        slug="cron",
        title="Cron",
        source=runs.SOURCE_APP,
    )
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


def test_list_and_metrics_exclude_non_app_pollution(client):
    """Re-extract / ad-hoc runs without source=concept-factory must not appear."""
    app = runs.new_run(
        kind="build",
        topicId="real-topic",
        slug="reinforcement-learning",
        title="Reinforcement Learning",
        source=runs.SOURCE_APP,
    )
    app.event({
        "type": "end",
        "sessionId": "sess-real",
        "usage": {"input_tokens": 10, "output_tokens": 5},
        "total_cost_usd": 0.025136,
    })
    app.finish("success")

    # Pollution shaped like prior verification clones: one end event, $0.57,
    # placeholder title — no app source.
    junk = runs.new_run(kind="build", topicId="x", slug="x", title="x", driver="grok")
    junk.event({
        "type": "end",
        "sessionId": "sess-cloned",
        "usage": {"input_tokens": 1, "output_tokens": 1},
        "total_cost_usd": 0.56947,
    })
    junk.finish("success")
    assert junk.record.get("source") in ("", None)

    listed = runs.list_runs()
    assert [r["id"] for r in listed] == [app.id]
    assert all(r.get("source") == runs.SOURCE_APP for r in listed)

    api_listed = client.get("/api/runs").json()["runs"]
    assert [r["id"] for r in api_listed] == [app.id]

    m = runs.metrics_summary()
    assert m["totalRuns"] == 1
    assert m["totalCostUsd"] == pytest.approx(0.025136)

    # app_only=False still sees pollution (internal / cleanup use)
    all_runs = runs.list_runs(app_only=False)
    assert {r["id"] for r in all_runs} == {app.id, junk.id}


def test_start_run_tags_app_source():
    """main._start_run is the only path that should create listed dashboard runs."""
    rec, emit = main._start_run("plan", "topic-1", "slug-1", "Title One")
    emit("hello")
    assert rec.record["source"] == runs.SOURCE_APP
    assert rec.record["kind"] == "plan"
    listed = runs.list_runs()
    assert any(r["id"] == rec.id for r in listed)
    rec.finish("success")


def test_reparse_cost_from_own_events_not_another_run():
    """Each run's cost comes from its own events stream."""
    plan = runs.new_run(
        kind="plan", topicId="t", slug="rl", title="RL", source=runs.SOURCE_APP
    )
    plan.event({
        "type": "end",
        "total_cost_usd": 0.025136,
        "usage": {"input_tokens": 100, "output_tokens": 20},
    })
    plan.finish("success")
    # Simulate pre-fix null cost on disk
    plan.record["costUsd"] = None
    (runs.RUNS_DIR / plan.id / "run.json").write_text(
        __import__("json").dumps(plan.record, indent=2) + "\n"
    )
    runs.reset_cache_for_tests()

    build = runs.new_run(
        kind="build", topicId="t", slug="rl", title="RL", source=runs.SOURCE_APP
    )
    build.event({
        "type": "end",
        "total_cost_usd": 0.56947,
        "usage": {"input_tokens": 1000, "output_tokens": 200},
    })
    build.finish("success")

    assert runs.reparse_cost_from_events(plan.id) == pytest.approx(0.025136)
    assert runs.get_run(plan.id)["costUsd"] == pytest.approx(0.025136)
    assert runs.get_run(build.id)["costUsd"] == pytest.approx(0.56947)
    m = runs.metrics_summary()
    assert m["totalCostUsd"] == pytest.approx(0.025136 + 0.56947)


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
