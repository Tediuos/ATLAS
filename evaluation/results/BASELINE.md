# Before / after: selected regression probes

Original commit: `a4389d84c29de13201664f1cd411c14087932e34`. Same scripted model and stubbed services for both implementations.

| Probe | Original | Current | Original / current read calls |
|---|---|---|---|
| audit_success | Pass | Pass | 1 / 1 |
| pause_before_write | Fail | Pass | 1 / 1 |
| unknown_tool | Fail | Pass | 1 / 0 |
| invalid_url | Fail | Pass | 1 / 0 |
| read_cache | Fail | Pass | 2 / 1 |
| iteration_budget | Fail | Pass | 1 / 1 |
| transient_tool_recovery | Fail | Pass | 1 / 2 |

Probe pass count: **1/7 -> 7/7**.

Seven selected regression probes, not an unbiased agent-quality benchmark. Model and external service boundaries are stubbed for both versions. Does not measure SEO performance, article quality, LLM accuracy or production latency.

The repeated-audit probe makes two identical requests. Memoization reduces read tool executions from two to one (50% in that specific fixture). This is not a measured latency or cost reduction.

Reproduce: `python -m atlas.evaluation.baseline` from a Git checkout containing the original commit.
