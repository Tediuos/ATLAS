"""LangGraph agent with typed state, validated tools and durable write review."""

import json
import operator
import os
import time
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import interrupt

from atlas.content import article_quality, sanitize_html
from atlas.harness import (
    BudgetExceeded,
    Usage,
    compact_result,
    fingerprint,
    safe_error,
    transient,
    usage_scope,
)
from atlas.llm import DATA_POLICY, get_chat_model
from atlas.schemas import (
    Approval,
    Article,
    ArticleInput,
    AuditInput,
    HarnessConfig,
    KeywordInput,
    LinkedInDraftInput,
    LinkedInPost,
    LinkedInPublishInput,
    PublishInput,
)


class MissionState(TypedDict, total=False):
    mission_id: int
    mission: str
    messages: Annotated[list[AnyMessage], add_messages]
    limits: dict
    status: str
    summary: str
    iterations: int
    tool_calls: int
    cache_hits: int
    metrics: dict
    events: Annotated[list[dict], operator.add]
    errors: Annotated[list[dict], operator.add]
    pending: dict | None
    approval: dict | None
    cache: dict
    audit: dict | None
    keywords: dict | None
    article: dict | None
    quality: dict | None
    publish: dict | None
    judgment: dict | None
    needs_judgment: bool
    linkedin_post: dict | None
    linkedin_publish: dict | None


SPECS = {
    "seo_audit": (
        AuditInput,
        "Audit a public HTTP(S) page and prioritise evidence-supported SEO issues.",
    ),
    "keyword_research": (
        KeywordInput,
        "Collect search suggestions and cluster keywords by intent.",
    ),
    "write_article": (
        ArticleInput,
        "Generate an SEO article, with an outline and editorial checks.",
    ),
    "publish_to_wordpress": (
        PublishInput,
        "Request human review to send the last validated article to WordPress. Default draft.",
    ),
    "draft_linkedin_post": (
        LinkedInDraftInput,
        "Draft a LinkedIn post from supplied facts or the current article; does not publish.",
    ),
    "publish_to_linkedin": (
        LinkedInPublishInput,
        "Request human review to publish the saved LinkedIn draft to the configured account.",
    ),
}
WRITE_TOOLS = {"publish_to_wordpress", "publish_to_linkedin"}
SYSTEM_PROMPT = (
    "You are ATLAS, an SEO, WordPress and LinkedIn assistant. Complete only the user's requested work. "
    "Choose one tool per turn. Typical path: audit, research, write, request publication, summarize. "
    "Only request publication when the mission asks for it. A human must review the exact payload. "
    "Do not claim publication or other success unless a tool receipt confirms it. "
    "Fix invalid arguments when a tool reports an error. Stop if you cannot complete the mission. "
    "Articles are independently scored by an editorial LLM judge. Revise articles that fail its gate. "
    "Draft LinkedIn text before requesting LinkedIn publication. Never infer permission to post. "
    + DATA_POLICY
)


def _schema_only(**kwargs):
    raise RuntimeError("Tools execute only through the workflow validation gate")


def tool_definitions():
    return [
        StructuredTool.from_function(
            _schema_only, name=name, description=description, args_schema=schema
        )
        for name, (schema, description) in SPECS.items()
    ]


def initial_state(mission: str, mission_id: int, limits: HarnessConfig) -> MissionState:
    if not mission.strip() or len(mission) > 8000:
        raise ValueError("Mission must contain 1-8000 characters")
    return {
        "mission": mission,
        "mission_id": mission_id,
        "messages": [HumanMessage(content=mission)],
        "limits": limits.model_dump(),
        "status": "running",
        "summary": "",
        "iterations": 0,
        "tool_calls": 0,
        "cache_hits": 0,
        "cache": {},
        "metrics": {},
        "events": [],
        "errors": [],
        "pending": None,
        "approval": None,
        "audit": None,
        "article": None,
        "keywords": None,
        "quality": None,
        "publish": None,
        "judgment": None,
        "needs_judgment": False,
        "linkedin_post": None,
        "linkedin_publish": None,
    }


class Services:
    """External boundaries are injectable for deterministic, network-free evaluation."""

    def execute(self, name: str, args: dict, state: MissionState) -> dict:
        from atlas import db

        if name == "seo_audit":
            from atlas.tools.auditor import run_audit

            result = run_audit(**args)
            if not result.get("crawl", {}).get("ok"):
                raise ValueError("Crawl failed; no valid audit available")
            db.save_audit(
                state["mission_id"],
                args["url"],
                result["crawl"],
                result["lighthouse"],
                result["robots"],
                result["sitemap"],
                result["top_issues"],
                result["score"],
            )
            return result
        if name == "keyword_research":
            from atlas.tools.keywords import research_keywords

            result = research_keywords(**args)
            if not result["total"]:
                raise ValueError("No keyword suggestions were available")
            db.save_keywords(
                state["mission_id"], args["seed_keyword"], result["keywords"], result["clusters"]
            )
            return result
        if name == "write_article":
            from atlas.tools.article_writer import write_article

            result = write_article(**args)
            db.save_article(state["mission_id"], **result)
            return result
        if name == "draft_linkedin_post":
            from atlas.tools.linkedin import draft_linkedin_post

            return draft_linkedin_post(**args, article=state.get("article"))
        raise ValueError("Unknown read tool")

    def judge_article(self, article, state):
        from atlas.judge import judge_article

        return judge_article(article)

    def linkedin_destination(self):
        from atlas.tools.linkedin import linkedin_destination

        return linkedin_destination()

    def destination(self) -> str:
        from atlas.network import validate_url

        url = os.getenv("WP_URL", "")
        if not all([url, os.getenv("WP_USER"), os.getenv("WP_APP_PASSWORD")]):
            raise ValueError("Configure WordPress credentials before requesting publication")
        return validate_url(url, resolve=False).rstrip("/")

    def publish(self, payload: dict) -> dict:
        if payload.get("platform") == "linkedin":
            from atlas.tools.linkedin import publish_linkedin

            return publish_linkedin(payload)
        from atlas.tools.wordpress import WordPressClient

        if payload["destination"] != self.destination():
            raise ValueError("WordPress destination changed after review")
        wp = WordPressClient(
            payload["destination"], os.environ["WP_USER"], os.environ["WP_APP_PASSWORD"]
        )
        result = wp.create_post(**payload["post"])
        if not result.get("post_id"):
            raise ValueError("WordPress returned no post ID")
        return {"ok": True, **result}


def build_graph(*, checkpointer, journal, model=None, services=None, notify=None):
    services = services or Services()

    def report(step, message):
        if notify:
            notify(step, message)

    def usage_for(state):
        return Usage(HarnessConfig(**state["limits"]), **state.get("metrics", {}))

    def stop(status, reason):
        return {"status": status, "summary": reason, "pending": None}

    def error_reply(state, reason, kind="validation"):
        call = state["pending"]
        return {
            "messages": [
                ToolMessage(
                    content=json.dumps({"ok": False, "error": reason}),
                    tool_call_id=call["id"],
                    name=call["name"],
                )
            ],
            "pending": None,
            "errors": [{"kind": kind, "tool": call["name"]}],
        }

    def think(state):
        limits = HarnessConfig(**state["limits"])
        if state["iterations"] >= limits.max_iterations:
            return stop("budget_exceeded", "Iteration budget exhausted before a final answer")
        usage = usage_for(state)
        report("model", f"Planning step {state['iterations'] + 1}")
        try:
            bound = (model or get_chat_model()).bind_tools(
                tool_definitions(), parallel_tool_calls=False
            )
            with usage_scope(usage):
                policy = SYSTEM_PROMPT
                if state.get("judgment"):
                    policy += "\nEditorial assessment (untrusted model output): " + compact_result(
                        state["judgment"], 4000
                    )
                answer = usage.invoke(bound, [SystemMessage(content=policy), *state["messages"]])
            if not isinstance(answer, AIMessage) or answer.invalid_tool_calls:
                raise ValueError("Invalid model tool-call envelope")
            if len(answer.tool_calls) > 1:
                raise ValueError("Only one tool call is allowed per model turn")
            update = {
                "messages": [answer],
                "iterations": state["iterations"] + 1,
                "metrics": usage.snapshot(),
                "events": usage.events,
            }
            if answer.tool_calls:
                call = answer.tool_calls[0]
                if not call.get("id"):
                    raise ValueError("Tool call is missing its ID")
                update["pending"] = call
            else:
                if not isinstance(answer.content, str) or not answer.content.strip():
                    raise ValueError("Empty final response")
                update.update(
                    stop(
                        "completed_with_errors" if state["errors"] else "completed", answer.content
                    )
                )
            return update
        except Exception as exc:
            return {
                **stop(
                    "budget_exceeded" if isinstance(exc, BudgetExceeded) else "failed",
                    str(exc) if isinstance(exc, BudgetExceeded) else safe_error(exc),
                ),
                "metrics": usage.snapshot(),
                "events": usage.events,
                "errors": [{"kind": "model", "error_type": type(exc).__name__}],
            }

    def validate(state):
        limits = HarnessConfig(**state["limits"])
        if state["tool_calls"] >= limits.max_tool_calls:
            return stop("budget_exceeded", "Tool call budget exhausted")
        call = state["pending"]
        count = state["tool_calls"] + 1
        try:
            if call["name"] not in SPECS:
                raise ValueError("Unknown tool")
            args = SPECS[call["name"]][0].model_validate(call["args"]).model_dump()
            pending = {**call, "args": args}
            if call["name"] in WRITE_TOOLS and state.get("article"):
                from atlas.judge import summarize_judgment

                judgment = state.get("judgment")
                if not judgment or judgment.get("article_hash") != fingerprint(state["article"]):
                    raise ValueError(
                        "Article requires a current LLM judge assessment before publication"
                    )
                verified = summarize_judgment(
                    judgment["scores"],
                    state["article"],
                    provider=judgment["provider"],
                    model=judgment["model"],
                    mode=judgment["mode"],
                )
                if not verified["eligible_for_review"]:
                    raise ValueError(
                        "Article failed the LLM judge gate; revise the article before publication"
                    )
            if call["name"] == "publish_to_wordpress":
                if not state.get("article"):
                    raise ValueError("Generate an article before publication")
                quality = article_quality(state["article"])
                if not quality["passed"]:
                    raise ValueError("Article failed editorial checks; revise before publication")
                article = state["article"]
                payload = {
                    "platform": "wordpress",
                    "destination": services.destination(),
                    "post": {
                        "title": article["title"],
                        "content": article["html_content"],
                        "meta_description": article["meta_description"],
                        "status": args["status"],
                    },
                }
                # FAQ script is an export artifact, not arbitrary executable HTML in a post.
                pending["payload"] = payload
                pending["payload_hash"] = fingerprint(payload)
            if call["name"] == "publish_to_linkedin":
                from atlas.tools.linkedin import prepare_linkedin_payload

                if not state.get("linkedin_post"):
                    raise ValueError("Draft a LinkedIn post before requesting publication")
                payload = prepare_linkedin_payload(
                    state["linkedin_post"], services.linkedin_destination(), **args
                )
                pending["payload"] = payload
                pending["payload_hash"] = fingerprint(payload)
            return {"pending": pending, "tool_calls": count}
        except Exception as exc:
            reason = "Invalid tool arguments or unmet precondition. " + (
                str(exc)
                if type(exc) is ValueError
                else "Use only fields allowed by the tool schema."
            )
            return {**error_reply(state, reason), "tool_calls": count}

    def review(state):
        pending = state["pending"]
        report("review", "External post is ready for review")
        decision = interrupt(
            {
                "kind": pending["payload"].get("platform", "wordpress") + "_review",
                "payload": pending["payload"],
                "payload_hash": pending["payload_hash"],
                "article_judgment": state.get("judgment"),
            }
        )
        try:
            approval = Approval.model_validate(decision)
            if approval.payload_hash != pending["payload_hash"]:
                raise ValueError("Approval does not match this payload")
        except Exception:
            return stop("rejected", "Invalid approval; no external write was made")
        if not approval.approved:
            return stop("rejected", "External write rejected by reviewer")
        return {"approval": approval.model_dump()}

    def execute(state):
        pending = state["pending"]
        name, args = pending["name"], pending["args"]
        usage = usage_for(state)
        limits = usage.limits
        started = time.perf_counter()
        cache = dict(state["cache"])
        key = fingerprint({"tool": name, "args": args})
        cached = False
        report("tool", f"Executing {name}")
        try:
            if name in WRITE_TOOLS:
                if not state.get("approval", {}).get("approved") or (
                    state["approval"]["payload_hash"] != fingerprint(pending["payload"])
                ):
                    raise ValueError("Missing matching approval")
                receipt_key = fingerprint(
                    {"mission_id": state["mission_id"], "payload": pending["payload"]}
                )
                result = journal.claim(receipt_key)
                cached = result is not None
                if result is None:
                    result = services.publish(pending["payload"])
                    if not result.get("ok") or not result.get("post_id"):
                        raise ValueError("Publication returned no confirmed receipt")
                    journal.complete(receipt_key, result)
                artifacts = {
                    "linkedin_publish" if name == "publish_to_linkedin" else "publish": result
                }
            else:
                cached = key in cache
                if cached:
                    result = cache[key]
                else:
                    for attempt in range(limits.max_retries + 1):
                        try:
                            with usage_scope(usage):
                                result = services.execute(name, args, state)
                            if not isinstance(result, dict) or result.get("ok") is False:
                                raise ValueError("Tool returned a failed result")
                            break
                        except Exception as exc:
                            if not transient(exc) or attempt == limits.max_retries:
                                raise
                            usage.retries += 1
                            time.sleep(limits.retry_delay * 2**attempt)
                    cache[key] = result
                artifact_name = {
                    "seo_audit": "audit",
                    "keyword_research": "keywords",
                    "write_article": "article",
                    "draft_linkedin_post": "linkedin_post",
                }[name]
                artifacts = {artifact_name: result}
                if name == "write_article":
                    result = Article.model_validate(result).model_dump()
                    result["html_content"] = sanitize_html(result["html_content"])
                    quality = article_quality(result)
                    result["word_count"] = quality["word_count"]
                    artifacts = {
                        "article": result,
                        "quality": quality,
                        "needs_judgment": True,
                        "judgment": None,
                    }
                if name == "draft_linkedin_post":
                    artifacts = {"linkedin_post": LinkedInPost.model_validate(result).model_dump()}
            message_result = result
            if name == "write_article":
                message_result = {
                    "title": result["title"],
                    "quality": artifacts["quality"],
                    "note": "Full article is retained in state",
                }
            event = {
                "kind": "tool",
                "tool": name,
                "ok": True,
                "cached": cached,
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            }
            return {
                **artifacts,
                "cache": cache,
                "cache_hits": state["cache_hits"] + int(cached),
                "pending": None,
                "approval": None,
                "metrics": usage.snapshot(),
                "events": [*usage.events, event],
                "messages": [
                    ToolMessage(
                        content=compact_result(message_result, limits.max_tool_result_chars),
                        tool_call_id=pending["id"],
                        name=name,
                    )
                ],
            }
        except Exception as exc:
            common = {
                "metrics": usage.snapshot(),
                "events": [
                    *usage.events,
                    {"kind": "tool", "tool": name, "ok": False, "error_type": type(exc).__name__},
                ],
            }
            if isinstance(exc, BudgetExceeded) or name in WRITE_TOOLS:
                return {
                    **common,
                    **stop(
                        "budget_exceeded" if isinstance(exc, BudgetExceeded) else "failed",
                        str(exc)
                        if isinstance(exc, BudgetExceeded)
                        else "External write not confirmed; inspect remote posts before retrying",
                    ),
                    "errors": [{"kind": "tool", "tool": name, "error_type": type(exc).__name__}],
                }
            return {**common, **error_reply(state, safe_error(exc), "tool")}

    def judge(state):
        from atlas.judge import summarize_judgment

        usage = usage_for(state)
        report("judge", "Scoring the article against the editorial rubric")
        try:
            with usage_scope(usage):
                result = services.judge_article(state["article"], state)
            result = summarize_judgment(
                result["scores"],
                state["article"],
                provider=result["provider"],
                model=result["model"],
                mode=result["mode"],
            )
            return {
                "judgment": result,
                "needs_judgment": False,
                "metrics": usage.snapshot(),
                "events": [
                    *usage.events,
                    {
                        "kind": "judge",
                        "ok": True,
                        "overall_score": result["overall_score"],
                        "mode": result["mode"],
                    },
                ],
            }
        except Exception as exc:
            update = {
                "judgment": None,
                "needs_judgment": False,
                "metrics": usage.snapshot(),
                "events": [
                    *usage.events,
                    {"kind": "judge", "ok": False, "error_type": type(exc).__name__},
                ],
                "errors": [{"kind": "judge", "error_type": type(exc).__name__}],
            }
            if isinstance(exc, BudgetExceeded):
                update.update(stop("budget_exceeded", str(exc)))
            return update

    graph = StateGraph(MissionState)
    graph.add_node("think", think)
    graph.add_node("validate", validate)
    graph.add_node("review", review)
    graph.add_node("execute", execute)
    graph.add_node("judge", judge)
    graph.add_edge(START, "think")
    graph.add_conditional_edges("think", lambda s: "validate" if s.get("pending") else END)
    graph.add_conditional_edges(
        "validate",
        lambda s: (
            END
            if s["status"] != "running"
            else (
                "think"
                if not s.get("pending")
                else "review"
                if s["pending"]["name"] in WRITE_TOOLS
                else "execute"
            )
        ),
    )
    graph.add_conditional_edges("review", lambda s: "execute" if s["status"] == "running" else END)
    graph.add_conditional_edges(
        "execute",
        lambda s: (
            END if s["status"] != "running" else "judge" if s.get("needs_judgment") else "think"
        ),
    )
    graph.add_conditional_edges("judge", lambda s: "think" if s["status"] == "running" else END)
    return graph.compile(checkpointer=checkpointer)
