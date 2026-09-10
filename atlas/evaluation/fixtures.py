"""Synthetic inputs and scripted providers; never contact external services."""

import copy

from langchain_core.messages import AIMessage


def tool_call(name, args=None, call_id="call-1"):
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args or {}, "id": call_id, "type": "tool_call"}],
    )


def article_fixture(keyword="wordpress seo"):
    paragraph = " ".join(
        ["Useful content helps readers understand the topic and take practical action."] * 28
    )
    html = f"<h1>A guide to {keyword}</h1><p>{keyword} supports a clear website strategy.</p>"
    html += "".join(f"<h2>Section {i}</h2><p>{paragraph}</p>" for i in range(4))
    from atlas.tools.article_writer import _count_words

    return {
        "target_keyword": keyword,
        "title": f"A guide to {keyword}",
        "html_content": html,
        "faq_json_ld": "",
        "word_count": _count_words(html),
        "meta_description": f"Explore {keyword} with practical advice for clear content, useful pages and a better website experience.",
    }


AUDIT = {
    "url": "https://example.com",
    "score": 75,
    "crawl": {"ok": True},
    "lighthouse": {"ok": True, "scores": {"seo": 90, "performance": 60}},
    "robots": {"ok": True, "exists": True},
    "sitemap": {"ok": True, "total_urls": 2},
    "top_issues": [
        {
            "priority": 1,
            "category": "on-page",
            "issue": "Missing description",
            "impact": "Less useful snippets",
            "recommendation": "Add a description",
            "effort": "low",
        }
    ],
}
KEYWORDS = {
    "seed": "wordpress seo",
    "total": 1,
    "keywords": [
        {
            "keyword": "wordpress seo",
            "cluster": "guides",
            "intent": "informational",
            "volume_rank": 5,
        }
    ],
    "clusters": {"guides": {"description": "SEO guides", "keywords": []}},
}


class ScriptedModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.seen = []

    def bind_tools(self, tools, **kwargs):
        self.tools = tools
        return self

    def invoke(self, messages):
        self.seen.append(messages)
        self.calls += 1
        if not self.responses:
            raise AssertionError("Scripted model exhausted")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return copy.deepcopy(response)


class FixtureServices:
    def __init__(
        self, *, failure=None, fail_count=0, article=None, judge_scores=None, judge_failure=None
    ):
        self.calls = []
        self.writes = []
        self.failure = failure
        self.fail_count = fail_count
        self.article = article
        self.judge_scores = judge_scores
        self.judge_failure = judge_failure
        self.judge_calls = 0

    def execute(self, name, args, state):
        self.calls.append(name)
        if self.fail_count:
            self.fail_count -= 1
            raise self.failure
        result = {
            "seo_audit": AUDIT,
            "keyword_research": KEYWORDS,
            "write_article": self.article
            or article_fixture(args.get("target_keyword", "wordpress seo")),
            "draft_linkedin_post": {
                "text": "A practical workflow starts with clear inputs, validated outputs and review before publishing."
            },
        }[name]
        return copy.deepcopy(result)

    def destination(self):
        return "https://wordpress.example"

    def publish(self, payload):
        self.writes.append(copy.deepcopy(payload))
        return {
            "ok": True,
            "post_id": 42,
            "link": "https://wordpress.example/?p=42",
            "status": payload["post"].get("status", "published"),
        }

    def judge_article(self, article, state):
        from atlas.judge import summarize_judgment

        self.judge_calls += 1
        if self.judge_failure:
            raise self.judge_failure
        return summarize_judgment(
            self.judge_scores or judge_scores_fixture(),
            article,
            provider="fixture",
            model="scripted-judge",
            mode="scripted",
        )

    def linkedin_destination(self):
        return {"author": "urn:li:person:fixture", "api_version": "202606"}


def judge_scores_fixture(score=4, recommendation="accept"):
    from atlas.judge import DIMENSIONS

    return {
        **{
            key: {
                "score": score,
                "rationale": "Synthetic rubric response for testing the scoring protocol.",
            }
            for key in DIMENSIONS
        },
        "recommendation": recommendation,
        "requires_fact_check": True,
        "concerns": [],
    }
