# Evaluation methodology

## What was measured

The recorded results evaluate this repository, including the agent workflow and its SEO, content, persistence and publishing components. They do not evaluate other repositories on the author's GitHub account.

Four complementary records are committed:

1. [Repository validation](../evaluation/results/VALIDATION.md): 117 automated tests, per-module statements and branches, and a Streamlit initial-render smoke test. Socket connections are blocked during tests. HTTP and model responses are injected fixtures.
2. [Workflow benchmark](../evaluation/results/RESULTS.md): 34 scripted scenarios, repeated five times, with observed statuses, tool counts, model counts and local graph latency.
3. [Historical comparison](../evaluation/results/BASELINE.md): seven selected regression probes against the original agent source from commit `a4389d84`.

4. [Judge protocol](../evaluation/results/JUDGE_PROTOCOL.md): 10 synthetic validation and scoring checks. Actual model-assigned article scores are recorded separately by the [live judge command](llm-judge.md).

The machine-readable records preserve counts, raw outcomes, environment versions and the source fingerprint. `requirements-lock.txt` records the installed package versions used locally. Results are observations from that run, not permanent performance guarantees.

## Success criteria and denominators

A scenario passes only when its terminal/paused status, executed read-tool count, executed write count, and no-write-before-approval assertion match the declared expectation. The planner and judge responses are scripted; ATLAS's graph and harness are real. The fixture service supplies deterministic data in place of HTTP, Lighthouse, provider generation, WordPress and LinkedIn calls.

Thus, **170/170 means 170 successful executions of 34 selected scenarios**. Repeats measure consistency; they are not 170 independent tasks. Fixture articles intentionally repeat text to exercise structure checks. Their passing score is not evidence of good writing.

The source fingerprint normalizes line endings and includes every Python file under `atlas/`, sorted by relative path. Coverage uses the full `atlas` package, including the evaluation programs and optional helpers. Streamlit is tested separately and is not part of that coverage denominator. The historical comparison runs separately, so its execution does not contribute to pytest coverage.

## Timing and caching

Timing starts immediately before `graph.invoke` and includes any scripted review/resume invocation. It excludes graph construction and all real external services. P50 is the median; P95 is the nearest-rank 95th percentile. The first invocation is included; there is no discarded warm-up. The environment is Python 3.12 on Windows for the committed snapshot.

The caching probe asks for the same audit twice. The original loop executes its service twice; the graph executes it once and reuses the mission-local result. This is a **50% reduction in tool executions for that repeated-call fixture**, not a measured cost or latency improvement across arbitrary missions.

## Historical comparison

The baseline loader reads the original file through `git show` and records its SHA-256. The original control loop is executed with a stubbed database, scripted OpenAI-shaped responses, and an injected dispatcher. The current graph gets the same scripts and service boundary. Neither implementation contacts a provider or website.

The seven probes cover an ordinary audit, write review, unknown tool, invalid URL, repeated audit, iteration exhaustion, and a transient failure. They were selected to test the newly introduced harness controls, so the **1/7 → 7/7** result is a regression comparison, not a broad agent-intelligence benchmark.

## Reproduce

From a full Git checkout with dependencies installed:

```bash
pytest --cov=atlas --cov-report=json:coverage.json --junitxml=test-results.xml
python -m atlas.evaluation.runner --repetitions 5
python -m atlas.evaluation.baseline
python -m atlas.evaluation.judge_run
python scripts/summarize_validation.py
```

The tests use an ignored `.pytest_tmp` directory in the repository to avoid OS-specific temporary-directory permissions. CI uploads the raw results for both supported Python versions. If editing source or fixtures, rerun the commands before updating any claims. Keep validation failures visible; never overwrite an expected outcome simply to make a benchmark pass.

## CV-ready wording

Use these as project descriptions, retaining the offline qualifier:

> Built a LangChain/LangGraph SEO, WordPress and LinkedIn agent with typed state, SQLite checkpoints, bounded model/tool execution, validated outputs and human-approved publishing; validated 34 offline workflow scenarios across 170 successful runs.

> Added 117 automated tests with 82.37% statement-and-branch coverage; improved seven selected reliability regression probes from 1/7 to 7/7 and reduced duplicate audit executions from two to one in a repeated-call fixture.

For a shorter CV, use the first bullet plus “117 automated tests.” The before/after denominator and fixture-specific caching result take more space to explain accurately.

## What remains unmeasured

Live provider tool-selection accuracy, article factuality, human editorial quality, provider tokens/cost per complete task, live WordPress behavior and end-to-end Lighthouse timing have not been measured. No search ranking, traffic, conversion or business impact has been established. Optional PDF output has not been rendered in this evaluation.

Before reporting live quality, build a versioned set of representative SEO missions and expected artifacts. Run it against a fixed model/provider configuration on a staging WordPress site, record failed as well as successful tasks, and keep retries in the cost denominator. Have reviewers score factual support, relevance, usefulness and editing effort using a written rubric. Measure production latency over complete tasks and record model version, sample size, website set, cache state and provider limits.

Live judge scores, when present, are model assessments from a small generated-article corpus. Report the article count, successful/requested judgments, model, rubric version and failure counts beside a mean score. The 10/10 protocol result is not evidence that a real model gave articles perfect scores.
