"""Hand-rolled tool-calling agent loop for Atlas SEO missions (no LangChain)."""
import json
import os
import re
from datetime import datetime
from typing import Any, Callable, Optional

from atlas import db
from atlas.llm import get_llm_client


# ------------------------------------------------------------------ #
#  Tool schemas (OpenAI function-calling format)                      #
# ------------------------------------------------------------------ #

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "seo_audit",
            "description": (
                "Run a complete SEO audit on a URL. Crawls the page, runs Lighthouse, "
                "checks robots.txt and sitemap, then uses AI to prioritise the top 10 issues."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Full URL to audit (must include http:// or https://).",
                    }
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "keyword_research",
            "description": (
                "Research keywords using Google Autocomplete and LLM semantic clustering. "
                "Returns ranked keywords with intent classification."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "seed_keyword": {
                        "type": "string",
                        "description": "Main keyword or topic to research.",
                    },
                    "language": {
                        "type": "string",
                        "description": "Language code (e.g. 'en', 'fr', 'de'). Default: 'en'.",
                    },
                },
                "required": ["seed_keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_article",
            "description": (
                "Write a full SEO-optimised HTML article (1200-1800 words) with FAQ JSON-LD. "
                "Uses two-pass outline → draft approach."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target_keyword": {
                        "type": "string",
                        "description": "Primary keyword to optimise the article for.",
                    },
                    "context": {
                        "type": "string",
                        "description": "Extra context from audit or keyword research.",
                    },
                    "audience": {
                        "type": "string",
                        "description": "Target audience description. Default: 'general'.",
                    },
                },
                "required": ["target_keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "publish_to_wordpress",
            "description": (
                "Publish an article to WordPress via the REST API. "
                "Reads WP_URL, WP_USER, WP_APP_PASSWORD from environment variables."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Post title.",
                    },
                    "content": {
                        "type": "string",
                        "description": "HTML body content. If omitted, uses the last written article.",
                    },
                    "meta_description": {
                        "type": "string",
                        "description": "SEO meta description.",
                    },
                    "status": {
                        "type": "string",
                        "description": "'draft' or 'publish'. Default: 'draft'.",
                    },
                },
                "required": ["title"],
            },
        },
    },
]

SYSTEM_PROMPT = """\
You are Atlas, an autonomous SEO and WordPress content agent.

Your goal: analyse websites, research keywords, write SEO-optimised articles, and publish them.

Typical workflow for a mission:
1. seo_audit — audit the target URL to understand current issues
2. keyword_research — find and cluster keywords for the main topic
3. write_article — write a 1200-1800 word article targeting the best keyword
4. publish_to_wordpress — publish as a draft (unless the user specifies otherwise)
5. Summarise what you accomplished and the key findings

Use all relevant tools to complete the mission. When finished, provide a concise summary.\
"""


# ------------------------------------------------------------------ #
#  Tool dispatcher                                                     #
# ------------------------------------------------------------------ #


def _dispatch_tool(
    name: str,
    args: dict,
    mission_id: int,
    article_cache: dict,
    audit_cache: dict,
    notify: Callable[[str, str], None],
) -> Any:
    """
    Dispatch a single tool call to the appropriate implementation.

    Args:
        name: Tool function name as declared in TOOLS.
        args: Parsed argument dict from the LLM.
        mission_id: Current mission ID for DB persistence.
        article_cache: Shared dict for caching the last written article.
        audit_cache: Shared dict for caching the last audit result.
        notify: Progress callback — notify(step_label, message).

    Returns:
        Tool result suitable for re-injection into the conversation as a
        tool-role message. Always a JSON-serialisable value.
    """
    if name == "seo_audit":
        from atlas.tools.auditor import run_audit

        url = args["url"]
        notify("seo_audit", f"Auditing {url}...")
        result = run_audit(url, mission_id=mission_id)
        audit_cache["last"] = result

        db.save_audit(
            mission_id=mission_id,
            url=url,
            crawl_data=result.get("crawl"),
            lighthouse_data=result.get("lighthouse"),
            robots_data=result.get("robots"),
            sitemap_data=result.get("sitemap"),
            issues=result.get("top_issues"),
            score=result.get("score"),
        )
        notify("seo_audit", f"Done. Score: {result.get('score')}/100")
        return {
            "url": url,
            "score": result.get("score"),
            "top_issues": (result.get("top_issues") or [])[:5],
            "lighthouse_scores": (result.get("lighthouse") or {}).get("scores"),
        }

    if name == "keyword_research":
        from atlas.tools.keywords import research_keywords

        seed = args["seed_keyword"]
        language = args.get("language", "en")
        notify("keyword_research", f"Researching: {seed}")
        result = research_keywords(seed, language=language)

        db.save_keywords(
            mission_id=mission_id,
            seed=seed,
            keywords=result.get("keywords", []),
            clusters=result.get("clusters", {}),
        )
        cluster_count = len(result.get("clusters", {}))
        notify("keyword_research", f"{result.get('total', 0)} keywords in {cluster_count} clusters")
        return {
            "seed": seed,
            "total": result.get("total"),
            "top_keywords": (result.get("keywords") or [])[:15],
            "cluster_names": list((result.get("clusters") or {}).keys()),
        }

    if name == "write_article":
        from atlas.tools.article_writer import write_article

        keyword = args["target_keyword"]
        context = args.get("context", "")
        audience = args.get("audience", "general")
        notify("write_article", f"Writing article for: {keyword}")
        result = write_article(keyword, context=context, audience=audience)
        article_cache["last"] = result

        article_id = db.save_article(
            mission_id=mission_id,
            target_keyword=keyword,
            title=result.get("title", ""),
            html_content=result.get("html_content", ""),
            faq_json_ld=result.get("faq_json_ld", ""),
            meta_description=result.get("meta_description", ""),
            word_count=result.get("word_count", 0),
        )
        article_cache["id"] = article_id
        notify("write_article", f"Done — {result.get('word_count')} words")
        return {
            "title": result.get("title"),
            "meta_description": result.get("meta_description"),
            "word_count": result.get("word_count"),
            "article_preview": (result.get("html_content") or "")[:500] + "...",
            "has_faq_schema": bool(result.get("faq_json_ld")),
        }

    if name == "publish_to_wordpress":
        from atlas.tools.wordpress import WordPressClient

        wp_url = os.getenv("WP_URL", "")
        wp_user = os.getenv("WP_USER", "")
        wp_password = os.getenv("WP_APP_PASSWORD", "")

        if not all([wp_url, wp_user, wp_password]):
            return {
                "ok": False,
                "error": "Missing WP_URL, WP_USER, or WP_APP_PASSWORD environment variables.",
            }

        title = args.get("title", "")
        content = args.get("content", "")
        meta_description = args.get("meta_description", "")
        status = args.get("status", "draft")

        if not content and article_cache.get("last"):
            cached = article_cache["last"]
            title = title or cached.get("title", "")
            html = cached.get("html_content", "")
            faq = cached.get("faq_json_ld", "")
            content = f"{html}\n\n{faq}".strip()
            meta_description = meta_description or cached.get("meta_description", "")

        if not content:
            return {"ok": False, "error": "No article content to publish. Run write_article first."}

        notify("publish_to_wordpress", f"Publishing to {wp_url}...")
        try:
            wp = WordPressClient(wp_url, wp_user, wp_password)
            result = wp.create_post(
                title=title,
                content=content,
                meta_description=meta_description,
                status=status,
            )
            article_id = article_cache.get("id", 0)
            db.save_publish_log(
                mission_id=mission_id,
                article_id=article_id,
                wp_post_id=result.get("post_id"),
                wp_url=result.get("link"),
                status="published",
            )
            notify("publish_to_wordpress", f"Published! Post ID: {result.get('post_id')}")
            return {"ok": True, **result}
        except Exception as exc:
            error_msg = str(exc)
            db.save_publish_log(
                mission_id=mission_id,
                article_id=article_cache.get("id", 0),
                status="failed",
                error=error_msg,
            )
            return {"ok": False, "error": error_msg}

    return {"error": f"Unknown tool: {name}"}


# ------------------------------------------------------------------ #
#  Main agent loop                                                     #
# ------------------------------------------------------------------ #


def run_mission(
    mission_text: str,
    max_iterations: int = 20,
    progress_callback: Optional[Callable[[str, str], None]] = None,
) -> dict:
    """
    Execute an Atlas SEO mission using a hand-rolled tool-calling loop.

    The loop follows the pattern from hello_agent.py:
        1. Serialise tool schemas → LLM
        2. Parse tool calls from LLM response
        3. Execute each tool
        4. Re-inject results as tool messages
        5. Repeat until the LLM returns a plain text final answer

    Args:
        mission_text: Natural language mission description. Should include a URL.
        max_iterations: Safety cap on the number of LLM round-trips.
        progress_callback: Optional callable(step_label, message) for live UI updates.

    Returns:
        Dict with mission_id, summary, article (last written), audit (last run).
    """
    client, model = get_llm_client()

    url_match = re.search(r"https?://[^\s]+", mission_text)
    target_url = url_match.group(0).rstrip(".,;:") if url_match else "https://example.com"

    mission_id = db.save_mission(text=mission_text, url=target_url)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": mission_text},
    ]

    article_cache: dict = {}
    audit_cache: dict = {}
    final_summary = ""

    def notify(step: str, msg: str) -> None:
        if progress_callback:
            progress_callback(step, msg)
        else:
            print(f"[Agent/{step}] {msg}")

    notify("init", f"Mission #{mission_id}: {mission_text[:80]}")

    for iteration in range(max_iterations):
        notify("loop", f"Iteration {iteration + 1}/{max_iterations}")

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
        )
        message = response.choices[0].message
        messages.append(message.model_dump(exclude_none=True))

        if not message.tool_calls:
            final_summary = message.content or ""
            notify("done", "Mission complete")
            break

        notify("tools", f"Executing {len(message.tool_calls)} tool call(s)")

        for tool_call in message.tool_calls:
            tool_name = tool_call.function.name
            try:
                args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                args = {}

            notify("dispatch", f"→ {tool_name}({list(args.keys())})")
            result = _dispatch_tool(
                tool_name, args, mission_id, article_cache, audit_cache, notify
            )

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(result, default=str),
            })
    else:
        final_summary = "Mission reached the iteration limit without a final answer."

    db.update_mission(
        mission_id,
        status="completed",
        completed_at=datetime.utcnow(),
        summary=final_summary,
    )

    return {
        "mission_id": mission_id,
        "summary": final_summary,
        "article": article_cache.get("last"),
        "audit": audit_cache.get("last"),
    }
