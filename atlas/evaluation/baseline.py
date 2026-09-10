"""Compare selected control-flow probes against the original committed agent.

Both implementations use the same scripted model and stubbed service boundary.
The baseline source is loaded from a fixed Git commit, never from the network.
"""

import argparse
import hashlib
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from atlas.evaluation.runner import run_scenario
from atlas.evaluation.scenarios import scenarios

BASELINE_COMMIT = "a4389d84c29de13201664f1cd411c14087932e34"
PROBES = {
    "audit_success",
    "read_cache",
    "iteration_budget",
    "unknown_tool",
    "invalid_url",
    "pause_before_write",
    "transient_tool_recovery",
}


def load_baseline():
    source = subprocess.run(
        ["git", "show", f"{BASELINE_COMMIT}:atlas/agent.py"], capture_output=True, check=True
    ).stdout
    namespace = {"__name__": "atlas_legacy_evaluation"}
    exec(compile(source, "legacy_agent.py", "exec"), namespace)
    return namespace, hashlib.sha256(source).hexdigest()


def run_legacy(namespace, scenario):
    model, services = scenario.dependencies()
    database = Mock()
    database.save_mission.return_value = 1
    namespace["db"] = database

    def create(**kwargs):
        answer = model.invoke([])
        calls = [
            SimpleNamespace(
                id=c["id"],
                function=SimpleNamespace(name=c["name"], arguments=json.dumps(c["args"])),
            )
            for c in answer.tool_calls
        ]
        message = SimpleNamespace(
            content=answer.content,
            tool_calls=calls,
            model_dump=lambda **kw: {"role": "assistant", "content": answer.content},
        )
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    namespace["get_llm_client"] = lambda: (
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
        "scripted",
    )

    def dispatch(name, args, mission_id, article_cache, audit_cache, notify):
        if name == "publish_to_wordpress":
            return services.publish({"post": {"status": "draft"}})
        return services.execute(name, args, {"mission_id": mission_id})

    namespace["_dispatch_tool"] = dispatch
    try:
        namespace["run_mission"](
            "Run the fixture SEO mission",
            max_iterations=scenario.limits.get("max_iterations", 12),
            progress_callback=lambda *a: None,
        )
        status = database.update_mission.call_args.kwargs["status"]
    except Exception as exc:
        status = f"raised:{type(exc).__name__}"
    checks = {
        "expected_status": status == scenario.expected_status,
        "read_count": len(services.calls) == scenario.expected_reads,
        "write_count": len(services.writes) == scenario.expected_writes,
    }
    return {
        "status": status,
        "read_calls": len(services.calls),
        "write_calls": len(services.writes),
        "checks": checks,
        "passed": all(checks.values()),
    }


def compare():
    namespace, source_hash = load_baseline()
    rows = []
    for scenario in scenarios():
        if scenario.name not in PROBES:
            continue
        before = run_legacy(namespace, scenario)
        with tempfile.TemporaryDirectory() as folder:
            after = run_scenario(scenario, Path(folder))
        rows.append(
            {
                "name": scenario.name,
                "expected_status": scenario.expected_status,
                "before": before,
                "after": after,
            }
        )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baseline_commit": BASELINE_COMMIT,
        "baseline_source_sha256": source_hash,
        "mode": "offline_scripted_control_flow",
        "probes": len(rows),
        "before_passed": sum(r["before"]["passed"] for r in rows),
        "after_passed": sum(r["after"]["passed"] for r in rows),
        "results": rows,
        "limitations": "Seven selected regression probes, not an unbiased agent-quality benchmark. "
        "Model and external service boundaries are stubbed for both versions. "
        "Does not measure SEO performance, article quality, LLM accuracy or production latency.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="evaluation/results")
    args = parser.parse_args()
    result = compare()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "baseline.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    lines = [
        "# Before / after: selected regression probes",
        "",
        f"Original commit: `{BASELINE_COMMIT}`. Same scripted model and stubbed services for both implementations.",
        "",
        "| Probe | Original | Current | Original / current read calls |",
        "|---|---|---|---|",
    ]
    for row in result["results"]:
        before, after = row["before"], row["after"]
        lines.append(
            f"| {row['name']} | {'Pass' if before['passed'] else 'Fail'} | "
            f"{'Pass' if after['passed'] else 'Fail'} | {before['read_calls']} / {after['read_calls']} |"
        )
    lines += [
        "",
        f"Probe pass count: **{result['before_passed']}/{result['probes']} -> "
        f"{result['after_passed']}/{result['probes']}**.",
        "",
        result["limitations"],
        "",
        "The repeated-audit probe makes two identical requests. Memoization reduces read tool "
        "executions from two to one (50% in that specific fixture). This is not a measured latency or cost reduction.",
        "",
        "Reproduce: `python -m atlas.evaluation.baseline` from a Git checkout containing the original commit.",
        "",
    ]
    (output / "BASELINE.md").write_text("\n".join(lines), encoding="utf-8")
    print(
        f"Selected probes: {result['before_passed']}/{result['probes']} -> {result['after_passed']}/{result['probes']}"
    )
    return 0 if result["after_passed"] == result["probes"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
