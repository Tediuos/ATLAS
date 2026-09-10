# Offline evaluation results

Generated: 2026-09-10T12:34:43.958811+00:00

**170/170 scenario runs passed**, across 34 distinct scenarios repeated 5 times.

| Category | Passed | Runs |
|---|---:|---:|
| approval | 25 | 25 |
| budget | 15 | 15 |
| cache | 5 | 5 |
| judge | 10 | 10 |
| linkedin | 40 | 40 |
| resilience | 25 | 25 |
| validation | 35 | 35 |
| workflow | 15 | 15 |

Local graph latency: p50 **6.91 ms**, p95 **21.88 ms** (scripted dependencies; not live execution).

Environment: Python 3.12.4 on Windows.

Source fingerprint (all `atlas/**/*.py`): `f1a276eb93bf57a42af613c7c412719998486ba3785f0b9c9f479d35b96bc869`

## Interpretation

- Scripted planner, judge and tool responses; no live provider, WordPress, LinkedIn or Lighthouse calls.
- Measures control flow and safety boundaries, not content quality, SEO uplift or model reasoning.
- Repeated runs test repeatability, not additional independent examples.
- Latencies exclude compilation and external services; no production speed claim.

Full inputs and expectations: `atlas/evaluation/scenarios.py`. Raw per-run results: [`latest.json`](latest.json). Reproduce with `python -m atlas.evaluation.runner --repetitions 5`.
