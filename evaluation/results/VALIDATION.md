# Repository validation

Generated: 2026-09-10T12:34:38.062509+00:00

Tests: **117**, failures: **0**, errors: **0**, skipped: **0**.

Coverage.py statement + branch coverage: **82.37%** (1448/1720 statements; 323/430 branches).

This is the complete `atlas` Python package, including evaluation utilities and optional legacy helpers. Streamlit has an AppTest smoke test; its source is outside this coverage denominator.

| Module | Statements executed / total | Branches covered / total | Combined coverage |
|---|---:|---:|---:|
| `atlas/agent.py` | 57/81 | 7/16 | 66.0% |
| `atlas/content.py` | 16/16 | 0/0 | 100.0% |
| `atlas/db.py` | 155/155 | 15/16 | 99.4% |
| `atlas/evaluation/__init__.py` | 0/0 | 0/0 | 100.0% |
| `atlas/evaluation/baseline.py` | 0/70 | 0/10 | 0.0% |
| `atlas/evaluation/fixtures.py` | 61/62 | 7/8 | 97.1% |
| `atlas/evaluation/judge_run.py` | 57/89 | 12/20 | 63.3% |
| `atlas/evaluation/runner.py` | 64/78 | 15/18 | 82.3% |
| `atlas/evaluation/scenarios.py` | 37/37 | 0/0 | 100.0% |
| `atlas/harness.py` | 77/79 | 18/20 | 96.0% |
| `atlas/journal.py` | 23/23 | 4/4 | 100.0% |
| `atlas/judge.py` | 28/28 | 1/2 | 96.7% |
| `atlas/llm.py` | 37/51 | 13/20 | 70.4% |
| `atlas/network.py` | 34/35 | 14/16 | 94.1% |
| `atlas/schemas.py` | 95/95 | 0/0 | 100.0% |
| `atlas/seo_report.py` | 17/31 | 3/8 | 51.3% |
| `atlas/tools/article_writer.py` | 33/33 | 4/4 | 100.0% |
| `atlas/tools/auditor.py` | 49/50 | 13/16 | 93.9% |
| `atlas/tools/crawler.py` | 95/105 | 32/40 | 87.6% |
| `atlas/tools/keywords.py` | 46/59 | 19/26 | 76.5% |
| `atlas/tools/lighthouse.py` | 51/70 | 15/22 | 71.7% |
| `atlas/tools/linkedin.py` | 34/36 | 10/12 | 91.7% |
| `atlas/tools/robots_sitemap.py` | 65/74 | 30/38 | 84.8% |
| `atlas/tools/wordpress.py` | 59/83 | 19/26 | 71.6% |
| `atlas/workflow.py` | 258/280 | 72/88 | 89.7% |

The historical-comparison CLI is exercised separately by the baseline command; that execution is not included in pytest coverage. Live provider quality, live WordPress, real Lighthouse timing and optional PDF rendering have not been validated in this run.
