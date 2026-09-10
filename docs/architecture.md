# Architecture

## Context and design

ATLAS is a local, single-user SEO assistant. The model chooses which of six tools to use; deterministic code controls whether and how those actions execute. The original manual loop had no durable conversational state, no publication review boundary, no shared model budget and no evaluation suite.

LangChain supplies chat messages, provider adapters, `StructuredTool` definitions, and schema-constrained model responses. LangGraph supplies the explicit execution graph, reducers, persistence and interrupts. A custom `StateGraph` is used because publication review, local artifact caching and write reconciliation need visible, testable transitions.

The implementation follows the documented [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence) and [interrupt/resume](https://docs.langchain.com/oss/python/langgraph/interrupts) APIs. Model contracts use [LangChain structured output](https://docs.langchain.com/oss/python/langchain/models#structured-output).

## State and transitions

`MissionState` is a typed dictionary. Its messages use `add_messages`; its error and event lists use append reducers. Other fields are replaced by node updates. This gives each checkpoint an inspectable representation of the latest artifacts, pending tool, review payload and budgets. Pydantic validates runtime data at model/tool/review boundaries; TypedDict annotations alone do not validate arbitrary state edits.

| Node | Responsibility | Next step |
|---|---|---|
| `think` | Check model limits, bind tool schemas, invoke model, validate call envelope | `validate` or end |
| `validate` | Tool allowlist, input contracts, tool budget, article prerequisites | `execute`, `review`, `think`, or end |
| `review` | Interrupt with exact WordPress/LinkedIn payload and judge assessment; require Boolean decision and matching SHA-256 | `execute` or rejected |
| `execute` | Read memoization, bounded transient retries, artifact updates, write receipt journal | `think`, `judge`, or failed/budget exceeded |
| `judge` | Score a generated article and derive review eligibility from validated rubric output | `think` or budget exceeded |

Only one tool call is accepted per planning step, making ordering explicit. A malformed envelope fails the mission. Invalid arguments return a structured error so the model can correct them within its remaining budget. A final answer after any recorded tool error is marked `completed_with_errors`, even if the model sounds confident.

`execute` routes generated articles through `judge` before the next planner call. The assessment is tied to the article hash. A missing or failed judgment blocks publication. Standalone LinkedIn drafts use the social tools without the article rubric. See [judge design](llm-judge.md).

Terminal statuses are `completed`, `completed_with_errors`, `budget_exceeded`, `failed` and `rejected`. A persisted interrupt is exposed as `awaiting_approval`. An exhausted loop never becomes a successful completion.

## Model harness

One `Usage` scope accounts for planner calls and nested audit/keyword/article calls. Its counters are written back into state after every node and restored on resume. Provider SDK retries are disabled so application retry accounting remains visible. Only transient network/timeouts, rate limits and selected server failures are retried, with exponential delays. Schema errors get one explicit model correction attempt. Article generation can get one separate editorial revision.

The model-attempt budget is a hard cap within an uninterrupted node execution. The token budget uses provider-reported usage and stops before a subsequent call; it is not a prepaid token reservation or a billing limit. Providers without usage reporting increment `unreported_usage_calls`. Token costs are not inferred from missing data. Read-node retries can repeat nested model work, but the shared call budget still applies.

Conversation input, including tool-call arguments, is bounded by serialized message characters, not tokenizer estimates. Static tool/schema definitions are outside that character count. Oversized context stops the mission rather than silently dropping earlier instructions. Tool observations are compacted as valid JSON; full artifacts stay in checkpoints. The source of an observation is treated as untrusted data in the model policy.

Events contain tool names, timing, success/failure and exception types. They omit provider response bodies and credentials. Checkpoints still contain messages and artifacts, so they are private state, not redacted telemetry.

## Persistence and external writes

- SQLAlchemy stores mission history, audits, keyword data and articles in `ATLAS_DB_PATH`.
- LangGraph's SQLite checkpointer stores workflow state under `ATLAS_STATE_DIR`.
- A separate SQLite write journal records a hash of the mission ID plus exact approved payload. Claiming a write is an atomic transaction with a unique key.

The write is claimed before the remote request. Once WordPress or LinkedIn confirms a post ID, its receipt is stored. Repeating the same payload within that mission returns the receipt. An unfinished claim is treated as uncertain and blocks replay. This covers a crash between remote success and checkpoint persistence without blindly creating another post.

There is no distributed transaction between SQLite and the publishing platform. A crash after the claim but before the request can also produce an uncertain record, even if no post exists. Availability is sacrificed in that case to avoid duplicate writes. An operator must inspect the publishing platform and reconcile the journal. Do not delete an uncertain journal entry merely to retry without checking the remote site.

`resume_mission` supports review interrupts. General crash recovery, concurrent workers, database migrations and distributed job scheduling are not implemented as public APIs. A process crash can repeat completed read work and lose usage counters since the last checkpoint; external writes use the separate journal to constrain replay.

## Tool and content boundaries

The WordPress publish tool accepts only a status; the LinkedIn publish tool accepts only public visibility. Its content comes from the validated article in state, not arbitrary model-supplied HTML. The review payload includes the destination and entire post body, title, metadata and status. Changing the configured destination after review prevents the write. A missing or failing article quality result prevents publication.

The eight editorial checks cover word count, one H1, keyword in H1, keyword in introduction, section count, meta-description length, keyword in metadata and absence of active HTML. They are structural checks, not judgments of originality, usefulness, factuality or ranking potential.

HTML is sanitized before review; reports escape untrusted strings. FAQ data is safely encoded and retained separately. URL validation blocks credentials, unsafe schemes and non-public DNS results unless local access is explicitly enabled. Each HTTP redirect is revalidated and response sizes are bounded. Sitemap traversal is capped by document count and page count and reports when totals are lower bounds.

Lighthouse runs via an argument list without a shell. On Windows, Node executes the installed JavaScript entry point directly. Browser subresources and DNS rebinding require network-level restrictions beyond this application's checks.

## Trade-offs and next steps

SQLite is easy to run locally, but a hosted multi-user version needs authenticated review endpoints, per-user credentials, access control on thread IDs and a transactional shared checkpointer. WordPress server-side idempotency would reduce manual reconciliation. Add live model evaluation and human editorial scoring before making content-quality claims. A bounded tool scheduler and per-node wall-time cancellation would improve long-running audits; current limits bound calls and individual I/O, not total mission duration.


## LinkedIn integration

The social path adds `draft_linkedin_post` and `publish_to_linkedin`. The first calls a structured text generator using the supplied facts and optional article. The second can only publish the stored draft to the configured member/organization URN. The versioned API body, author and visibility are included in the review hash. Changing the configured author or API version after review prevents the request. Access tokens are read at execution and never stored in the payload.

The client calls LinkedIn's fixed Posts API endpoint with a 30-second timeout, no redirects and one POST attempt. Only HTTP 201 with a valid `x-restli-id` is treated as a confirmed receipt. OAuth setup, token refresh, images and scheduling are not implemented. Live integration still requires a suitably authorized account and token.
