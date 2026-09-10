"""Turn actual pytest/coverage output into a small, shareable measurement record."""

import argparse
import json
import platform
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage", default="coverage.json")
    parser.add_argument("--junit", default="test-results.xml")
    parser.add_argument("--output", default="evaluation/results")
    args = parser.parse_args()
    coverage = json.loads(Path(args.coverage).read_text(encoding="utf-8"))
    suites = ET.parse(args.junit).getroot().findall("testsuite")
    totals = coverage["totals"]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "platform": platform.system(),
        "tests": sum(int(s.get("tests", 0)) for s in suites),
        "failures": sum(int(s.get("failures", 0)) for s in suites),
        "errors": sum(int(s.get("errors", 0)) for s in suites),
        "skipped": sum(int(s.get("skipped", 0)) for s in suites),
        "test_duration_s": round(sum(float(s.get("time", 0)) for s in suites), 3),
        "coverage": totals,
        "modules": {
            name.replace("\\", "/"): value["summary"] for name, value in coverage["files"].items()
        },
    }
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = [
        "# Repository validation",
        "",
        f"Generated: {report['generated_at']}",
        "",
        f"Tests: **{report['tests']}**, failures: **{report['failures']}**, errors: **{report['errors']}**, skipped: **{report['skipped']}**.",
        "",
        f"Coverage.py statement + branch coverage: **{totals['percent_covered']:.2f}%** "
        f"({totals['covered_lines']}/{totals['num_statements']} statements; "
        f"{totals['covered_branches']}/{totals['num_branches']} branches).",
        "",
        "This is the complete `atlas` Python package, including evaluation utilities and optional legacy helpers. "
        "Streamlit has an AppTest smoke test; its source is outside this coverage denominator.",
        "",
        "| Module | Statements executed / total | Branches covered / total | Combined coverage |",
        "|---|---:|---:|---:|",
    ]
    for name, value in report["modules"].items():
        lines.append(
            f"| `{name}` | {value['covered_lines']}/{value['num_statements']} | "
            f"{value.get('covered_branches', 0)}/{value.get('num_branches', 0)} | {value['percent_covered']:.1f}% |"
        )
    lines += [
        "",
        "The historical-comparison CLI is exercised separately by the baseline command; "
        "that execution is not included in pytest coverage. Live provider quality, live WordPress, "
        "real Lighthouse timing and optional PDF rendering have not been validated in this run.",
        "",
    ]
    (output / "VALIDATION.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"{report['tests']} tests; {totals['percent_covered']:.2f}% combined coverage")


if __name__ == "__main__":
    main()
