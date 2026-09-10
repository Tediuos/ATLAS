# Article evaluation with an LLM judge

## Pipeline

After `write_article`, LangGraph routes to `judge`. A separate evaluator call receives the generated article, keyword and description as data. The judge uses temperature 0 and returns a Pydantic `JudgeScores` response with five scores, rationales, concerns, a recommendation and a fact-check flag. It does not rewrite or publish content.

`JUDGE_PROVIDER=groq` and `JUDGE_MODEL` select the evaluator independently from the writer's model settings. The evaluator shares the mission's call/token budget and retry handling. A missing provider key, invalid response, or exhausted budget cannot silently become a passing score.

## Rubric `atlas-article-v1`

| Dimension | What it assesses |
|---|---|
| Relevance | Answers the target question for the intended audience |
| Clarity | Precise, readable prose without repetition or filler |
| Structure | Coherent headings, organization and progression |
| SEO | Useful metadata and natural keyword use |
| Factual support | Support for claims in the supplied evidence |

Each dimension uses integer scores from 1 to 5: unusable/unsupported, major weaknesses, acceptable with material edits, strong with minor edits, excellent with specific justification. Rationales are required. Boolean/string scores, out-of-range values and extra fields are rejected.

Code computes the overall score as `sum(five scores) / 25 * 100`. There are no model-provided weights or overall totals to trust. Scores therefore range from 20 to 100 before any evidence policy. Without evidence, code caps factual support at 3 and sets `requires_fact_check=true`, even if the model reports full confidence.

The current automatic workflow supplies no independently verified evidence corpus. Consequently, its assessments always flag human fact checking. Passing the review eligibility gate requires an overall score of at least 70, every dimension at least 3 and an `accept` recommendation. This makes a post eligible for human review; it does not authorize publication or certify truth.

## Provenance and gates

The saved assessment contains the rubric version, exact article hash, evidence hash, provider/model, timestamp, mode, dimension scores, rationales and derived overall score. Publication checks that the assessment matches the current article. Rewriting the article invalidates its previous assessment. Both WordPress and LinkedIn publication of missions containing an article require the current assessment to pass.

LinkedIn drafts created independently of an article do not receive this article rubric; they still require exact-payload human review. A LinkedIn post derived from an article inherits the article gate, but its final wording still needs human review.

## Recorded evaluation

- `judge_protocol.json` contains 10 deterministic checks of schema rejection, score arithmetic, evidence capping and recommendation precedence. They use synthetic judge responses and make no live model calls.
- `judge_live.json`, produced by `python -m atlas.evaluation.judge_run --live`, contains real generated articles, judge responses, failure counts, token usage, dimension means and within-article score variation across repetitions.
- `latest.json` records workflow behavior with scripted planner and judge responses, including judge failures and rejected articles.

By default, the live command generates three articles and obtains two judgments per article. Failures stay in the denominator. The mean score is computed only over successful judgments; the success count is reported beside it. The mean repeated-score range uses only articles with at least two successful judgments. Use `--articles path.json` to evaluate a JSON list of previously generated article artifacts instead.

When no provider credential is configured, no live score is recorded. The README distinguishes the synthetic checks from live article assessments.

## Limitations and calibration

LLM judges can favor verbosity or outputs resembling their own style; these limitations are discussed in [Zheng et al., Judging LLM-as-a-Judge](https://arxiv.org/abs/2306.05685). A separate call is not necessarily an independent model, and temperature 0 does not establish deterministic behavior. The default writer and judge can be the same model family.

No human-label calibration, factual verification, ranking correlation or business-impact validation has been measured here. The threshold of 70 is an engineering policy, not a statistically calibrated quality boundary. The article prompt explicitly treats embedded instructions as data, but the test suite does not prove universal resistance to prompt injection.

Before using judge scores as a production quality metric, collect representative articles with blinded human ratings, compare model/human agreement by dimension, review false accepts and false rejects, and repeat the comparison across different judge models. Keep the rubric, corpus and provider versions fixed while comparing changes.
