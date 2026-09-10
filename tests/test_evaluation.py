from atlas.evaluation.runner import evaluate, render_report


def test_evaluation_report_is_reproducible_and_labeled():
    report = evaluate(1)
    assert report["passed"] == report["runs"] == 34
    assert report["mode"] == "offline_scripted"
    assert report["latency_ms"]["p95"] >= report["latency_ms"]["p50"]
    assert len(report["source_sha256"]) == 64
    assert "not live execution" in render_report(report)
