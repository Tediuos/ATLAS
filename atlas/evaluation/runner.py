"""Run offline graph scenarios and write machine-readable and Markdown evidence."""

import argparse
import hashlib
import importlib.metadata
import json
import math
import platform
import statistics
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from atlas.evaluation.scenarios import scenarios
from atlas.journal import WriteJournal
from atlas.schemas import HarnessConfig
from atlas.workflow import build_graph, initial_state


def run_scenario(scenario, directory):
    model, services = scenario.dependencies()
    graph = build_graph(
        checkpointer=InMemorySaver(),
        journal=WriteJournal(directory / "writes.db"),
        model=model,
        services=services,
    )
    limits = HarnessConfig(retry_delay=0, **scenario.limits)
    config = {"configurable": {"thread_id": scenario.name}, "recursion_limit": 250}
    start = time.perf_counter()
    state = graph.invoke(initial_state("Run the fixture SEO mission", 1, limits), config)
    paused_without_write = True
    if state.get("__interrupt__"):
        paused_without_write = not services.writes
        if scenario.decision:
            payload_hash = state["__interrupt__"][0].value["payload_hash"]
            decision = {"approved": scenario.decision != "reject", "payload_hash": payload_hash}
            if scenario.decision == "forged":
                decision["payload_hash"] = "0" * 64
            if scenario.decision == "string":
                decision["approved"] = "true"
            state = graph.invoke(Command(resume=decision), config)
    elapsed = (time.perf_counter() - start) * 1000
    status = "awaiting_approval" if state.get("__interrupt__") else state["status"]
    checks = {
        "expected_status": status == scenario.expected_status,
        "read_count": len(services.calls) == scenario.expected_reads,
        "write_count": len(services.writes) == scenario.expected_writes,
        "no_write_before_approval": paused_without_write,
    }
    return {
        "name": scenario.name,
        "category": scenario.category,
        "passed": all(checks.values()),
        "checks": checks,
        "status": status,
        "expected_status": scenario.expected_status,
        "latency_ms": round(elapsed, 3),
        "read_calls": len(services.calls),
        "write_calls": len(services.writes),
        "cache_hits": state["cache_hits"],
        "model_calls": model.calls,
        "judge_calls": services.judge_calls,
        "metrics": state["metrics"],
    }


def source_hash():
    digest = hashlib.sha256()
    for path in sorted(Path("atlas").rglob("*.py")):
        digest.update(path.as_posix().encode())
        digest.update(path.read_text(encoding="utf-8").encode("utf-8"))
    return digest.hexdigest()


def evaluate(repetitions=5):
    rows = []
    for repetition in range(repetitions):
        for scenario in scenarios():
            with tempfile.TemporaryDirectory() as folder:
                row = run_scenario(scenario, Path(folder))
            rows.append({"repetition": repetition + 1, **row})
    elapsed = sorted(row["latency_ms"] for row in rows)
    counts = {
        category: {
            "passed": sum(r["passed"] for r in rows if r["category"] == category),
            "total": sum(r["category"] == category for r in rows),
        }
        for category in sorted({r["category"] for r in rows})
    }
    return {
        "schema_version": 1,
        "mode": "offline_scripted",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "platform": platform.system(),
        "dependencies": {
            name: importlib.metadata.version(name)
            for name in (
                "langchain",
                "langgraph",
                "langgraph-checkpoint-sqlite",
                "langchain-openai",
            )
        },
        "source_sha256": source_hash(),
        "repetitions": repetitions,
        "distinct_scenarios": len(scenarios()),
        "runs": len(rows),
        "passed": sum(r["passed"] for r in rows),
        "categories": counts,
        "latency_ms": {
            "p50": statistics.median(elapsed),
            "p95": elapsed[math.ceil(len(elapsed) * 0.95) - 1],
        },
        "limitations": [
            "Scripted planner, judge and tool responses; no live provider, WordPress, LinkedIn or Lighthouse calls.",
            "Measures control flow and safety boundaries, not content quality, SEO uplift or model reasoning.",
            "Repeated runs test repeatability, not additional independent examples.",
            "Latencies exclude compilation and external services; no production speed claim.",
        ],
        "results": rows,
    }


def render_report(report):
    lines = [
        "# Offline evaluation results",
        "",
        f"Generated: {report['generated_at']}",
        "",
        f"**{report['passed']}/{report['runs']} scenario runs passed**, across "
        f"{report['distinct_scenarios']} distinct scenarios repeated {report['repetitions']} times.",
        "",
        "| Category | Passed | Runs |",
        "|---|---:|---:|",
    ]
    lines += [
        f"| {key} | {value['passed']} | {value['total']} |"
        for key, value in report["categories"].items()
    ]
    lines += [
        "",
        f"Local graph latency: p50 **{report['latency_ms']['p50']:.2f} ms**, "
        f"p95 **{report['latency_ms']['p95']:.2f} ms** (scripted dependencies; not live execution).",
        "",
        f"Environment: Python {report['python']} on {report['platform']}.",
        "",
        f"Source fingerprint (all `atlas/**/*.py`): `{report['source_sha256']}`",
        "",
        "## Interpretation",
        "",
    ]
    lines += [f"- {line}" for line in report["limitations"]]
    lines += [
        "",
        "Full inputs and expectations: `atlas/evaluation/scenarios.py`. Raw per-run results: "
        "[`latest.json`](latest.json). Reproduce with `python -m atlas.evaluation.runner --repetitions 5`.",
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--output", default="evaluation/results")
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("repetitions must be positive")
    report = evaluate(args.repetitions)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (output / "RESULTS.md").write_text(render_report(report), encoding="utf-8")
    print(
        f"{report['passed']}/{report['runs']} passed; p50={report['latency_ms']['p50']:.2f}ms, "
        f"p95={report['latency_ms']['p95']:.2f}ms"
    )
    return 0 if report["passed"] == report["runs"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
