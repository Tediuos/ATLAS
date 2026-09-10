"""Separate synthetic judge-protocol checks from actual generated-article judging."""

import argparse
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from atlas.evaluation.fixtures import article_fixture, judge_scores_fixture
from atlas.harness import Usage, safe_error, usage_scope
from atlas.judge import DIMENSIONS, RUBRIC_VERSION, judge_article, summarize_judgment
from atlas.schemas import HarnessConfig, JudgeScores

TOPICS = [
    "wordpress seo basics",
    "accessible website content",
    "editorial workflow for small teams",
]


def protocol_evaluation():
    article = article_fixture()
    rows = []
    for score in range(1, 6):
        result = summarize_judgment(
            judge_scores_fixture(score),
            article,
            provider="fixture",
            model="scripted",
            mode="scripted",
        )
        expected = (4 * score + min(3, score)) / 25 * 100
        rows.append(
            {
                "name": f"aggregate_score_{score}",
                "passed": result["overall_score"] == expected
                and result["eligible_for_review"] == (score >= 4)
                and result["scores"]["requires_fact_check"],
            }
        )
    for invalid in (0, 6, "5", True):
        scores = judge_scores_fixture()
        scores["clarity"]["score"] = invalid
        try:
            JudgeScores.model_validate(scores)
            rejected = False
        except ValidationError:
            rejected = True
        rows.append({"name": f"reject_invalid_score_{invalid!r}", "passed": rejected})
    scores = judge_scores_fixture(5, "reject")
    result = summarize_judgment(
        scores, article, provider="fixture", model="scripted", mode="scripted"
    )
    rows.append(
        {"name": "reject_overrides_high_scores", "passed": not result["eligible_for_review"]}
    )
    return {
        "mode": "scripted_protocol",
        "rubric_version": RUBRIC_VERSION,
        "cases": len(rows),
        "passed": sum(row["passed"] for row in rows),
        "results": rows,
        "live_articles_scored": 0,
        "limitation": "Tests validation, arithmetic and gating with synthetic responses; not LLM judging quality.",
    }


def live_evaluation(samples=3, repetitions=2, articles=None):
    """Actually generate articles and call the configured judge. Retain failures in counts."""
    from atlas.content import article_quality
    from atlas.tools.article_writer import write_article

    usage = Usage(HarnessConfig(max_model_calls=60, max_tokens=100000, max_context_chars=64000))
    rows, corpus = [], []
    for index in range(samples):
        topic = TOPICS[index % len(TOPICS)]
        try:
            with usage_scope(usage):
                article = (
                    articles[index]
                    if articles
                    else write_article(topic, audience="small business owners")
                )
            corpus.append(article)
        except Exception as exc:
            rows.append(
                {"sample": index + 1, "stage": "generation", "ok": False, "error": safe_error(exc)}
            )
            continue
        for repetition in range(repetitions):
            try:
                with usage_scope(usage):
                    judgment = judge_article(article)
                rows.append(
                    {
                        "sample": index + 1,
                        "repetition": repetition + 1,
                        "stage": "judge",
                        "ok": True,
                        "structural_checks": article_quality(article),
                        "judgment": judgment,
                    }
                )
            except Exception as exc:
                rows.append(
                    {
                        "sample": index + 1,
                        "repetition": repetition + 1,
                        "stage": "judge",
                        "ok": False,
                        "error": safe_error(exc),
                    }
                )
    judged = [row for row in rows if row["ok"] and row["stage"] == "judge"]
    scores = [row["judgment"]["overall_score"] for row in judged]
    stability = []
    for sample in range(1, samples + 1):
        values = [row["judgment"]["overall_score"] for row in judged if row["sample"] == sample]
        if len(values) >= 2:
            stability.append(max(values) - min(values))
    return {
        "mode": "live_llm_judge",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rubric_version": RUBRIC_VERSION,
        "requested_articles": samples,
        "generated_articles": len(corpus),
        "requested_judgments": samples * repetitions,
        "successful_judgments": len(judged),
        "failed_operations": sum(not row["ok"] for row in rows),
        "repetitions": repetitions,
        "mean_score": round(statistics.mean(scores), 2) if scores else None,
        "min_score": min(scores) if scores else None,
        "max_score": max(scores) if scores else None,
        "eligible_judgments": sum(row["judgment"]["eligible_for_review"] for row in judged),
        "dimension_means": {
            key: round(
                statistics.mean(row["judgment"]["scores"][key]["score"] for row in judged), 2
            )
            for key in DIMENSIONS
        }
        if judged
        else {},
        "mean_repeat_score_range": round(statistics.mean(stability), 2) if stability else None,
        "usage": usage.snapshot(),
        "articles": corpus,
        "results": rows,
        "limitations": [
            "LLM-assigned rubric scores; no human calibration or verified factual correctness.",
            "Repeated judgments measure score variation, not independent article samples.",
            "Same-family writer/judge bias is possible; record both model configurations.",
            "No ranking, traffic, engagement or business impact measured.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--articles", help="Optional JSON list of actual article artifacts")
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--output", default="evaluation/results")
    args = parser.parse_args()
    if not 1 <= args.samples <= 10 or not 1 <= args.repetitions <= 5:
        parser.error("samples must be 1-10 and repetitions 1-5")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    if not args.live:
        result = protocol_evaluation()
        (output / "judge_protocol.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        (output / "JUDGE_PROTOCOL.md").write_text(
            f"# LLM judge protocol evaluation\n\n**{result['passed']}/{result['cases']} synthetic protocol checks passed.**\n\n"
            "Checks score ranges/types, deterministic aggregation, evidence-free score capping and rejection gates. "
            "These are tests of the judge harness, not scores assigned by a real LLM.\n\n"
            "Run `python -m atlas.evaluation.judge_run --live` after configuring Groq to generate and judge actual articles.\n",
            encoding="utf-8",
        )
        print(f"Judge protocol: {result['passed']}/{result['cases']} passed; no live model calls")
        return int(result["passed"] != result["cases"])
    articles = (
        json.loads(Path(args.articles).read_text(encoding="utf-8")) if args.articles else None
    )
    if articles is not None and len(articles) < args.samples:
        parser.error("The article input file contains fewer entries than --samples")
    result = live_evaluation(args.samples, args.repetitions, articles)
    (output / "judge_live.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    text = (
        f"# Live LLM-as-judge article evaluation\n\nGenerated: {result['generated_at']}\n\n"
        f"Articles generated: **{result['generated_articles']}/{result['requested_articles']}**. "
        f"Successful judgments: **{result['successful_judgments']}/{result['requested_judgments']}**.\n\n"
        f"Mean rubric score: **{result['mean_score']} / 100**. "
        f"Eligible for human review: **{result['eligible_judgments']}** judgments.\n\n"
        + "\n".join("- " + item for item in result["limitations"])
        + "\n"
    )
    (output / "JUDGE_LIVE.md").write_text(text, encoding="utf-8")
    print(
        f"Live judgments: {result['successful_judgments']}/{result['requested_judgments']}; mean={result['mean_score']}"
    )
    return int(result["successful_judgments"] != result["requested_judgments"])


if __name__ == "__main__":
    raise SystemExit(main())
