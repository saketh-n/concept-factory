"""Seed synthetic run records for UI verification (no agent, no credits).

Usage: .venv/bin/python seed_test_runs.py [--clean]
--clean removes previously seeded runs (identified by topicId prefix cf-test-).
"""
import random
import sys
import time

import runs

SEED_TOPIC_PREFIX = "cf-test-"


def clean() -> int:
    import shutil

    removed = 0
    for meta in runs.RUNS_DIR.glob("*/run.json"):
        try:
            import json

            rec = json.loads(meta.read_text())
        except Exception:
            continue
        if str(rec.get("topicId", "")).startswith(SEED_TOPIC_PREFIX):
            shutil.rmtree(meta.parent, ignore_errors=True)
            removed += 1
    runs.reset_cache_for_tests()
    return removed


def seed() -> None:
    random.seed(42)
    topics = [
        ("hash-tables", "Hash Tables"),
        ("tcp-handshake", "TCP Handshake"),
        ("regex-drills", "Regex Drills"),
        ("cron-syntax", "Cron Syntax"),
        ("tar-basics", "tar Basics"),
    ]
    kinds = ["plan", "plan", "build", "build", "improve", "refine", "consolidate"]
    now = time.time()
    for i in range(14):
        slug, title = topics[i % len(topics)]
        kind = kinds[i % len(kinds)]
        rec = runs.new_run(
            kind=kind,
            topicId=f"{SEED_TOPIC_PREFIX}{i}",
            slug=slug,
            title=title,
            source=runs.SOURCE_APP,  # intentional UI fixtures, not pollution
        )
        driver = "claude" if i % 3 else "grok"
        rec.update(
            driver=driver,
            driverLabel="Claude Code" if driver == "claude" else "Grok Build",
            model="claude-fable-5" if driver == "claude" else "grok-4.5",
            permissionMode="bypassPermissions",
        )
        n_tools = random.randint(4, 60 if kind in ("build", "improve") else 14)
        for _ in range(n_tools):
            rec.event(
                {
                    "type": "assistant",
                    "session_id": f"sess-{i}",
                    "message": {"content": [{"type": "tool_use", "name": "Bash"}]},
                }
            )
        rec.line(f"Driver: {driver} run for {title}")
        rec.line("Working…")
        rec.event(
            {
                "type": "result",
                "subtype": "success",
                "session_id": f"sess-{i}",
                "num_turns": n_tools + random.randint(2, 8),
                "total_cost_usd": round(random.uniform(0.02, 2.4), 4),
                "usage": {
                    "input_tokens": random.randint(800, 9000),
                    "output_tokens": random.randint(2000, 40000),
                    "cache_read_input_tokens": random.randint(10000, 300000),
                    "cache_creation_input_tokens": random.randint(500, 8000),
                },
            }
        )
        if i in (5, 9):
            rec.retry()
        failed = i in (3, 11)
        if kind in ("build", "improve"):
            rec.set_gate("build", {"status": "fail" if failed else "pass", "detail": ""})
            rec.set_gate(
                "lint",
                {"status": "skipped", "detail": "build failed"}
                if failed
                else {"status": "pass" if i % 4 else "fail", "detail": "" if i % 4 else "2 errors"},
            )
            total = random.randint(10, 18)
            passed = total if i % 5 else total - random.randint(1, 4)
            rec.set_gate(
                "validator",
                {"status": "skipped", "detail": "build failed"}
                if failed
                else {
                    "status": "pass" if passed == total else "fail",
                    "passed": passed,
                    "total": total,
                    "passRate": round(passed / total, 4),
                    "levels": [
                        {"id": n + 1, "topic": f"key-{n % 4}", "ok": n < passed,
                         "reason": "" if n < passed else "expected 'x', validator rejected canonical answer"}
                        for n in range(total)
                    ],
                },
            )
        rec.finish(
            "error" if failed else "success",
            error="Improvement broke the build; nothing was committed." if failed else "",
            exit_code=1 if failed else 0,
        )
        # Spread startedAt over the past 3 days for realistic charts.
        rec.record["startedAt"] = now - (14 - i) * 7200 - random.randint(0, 3000)
        rec.record["startedAtIso"] = runs._iso(rec.record["startedAt"])
        rec.record["durationSeconds"] = round(random.uniform(35, 1400), 1)
        (rec.dir / "run.json").write_text(
            __import__("json").dumps(rec.record, indent=2) + "\n"
        )
    runs.reset_cache_for_tests()
    print(f"seeded 14 runs into {runs.RUNS_DIR}")


if __name__ == "__main__":
    if "--clean" in sys.argv:
        print(f"removed {clean()} seeded runs")
    else:
        seed()
