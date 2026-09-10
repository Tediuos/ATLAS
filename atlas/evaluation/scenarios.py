"""Behavioral expectations for orchestration, independent of LLM intelligence."""

from dataclasses import dataclass, field

from langchain_core.messages import AIMessage

from atlas.evaluation.fixtures import FixtureServices, ScriptedModel, article_fixture, tool_call


@dataclass
class Scenario:
    name: str
    category: str
    responses: list
    expected_status: str
    expected_reads: int
    expected_writes: int = 0
    limits: dict = field(default_factory=dict)
    decision: str | None = None
    failure: Exception | None = None
    fail_count: int = 0
    article: dict | None = None
    judge_scores: dict | None = None
    judge_failure: Exception | None = None

    def dependencies(self):
        return ScriptedModel(self.responses), FixtureServices(
            failure=self.failure,
            fail_count=self.fail_count,
            article=self.article,
            judge_scores=self.judge_scores,
            judge_failure=self.judge_failure,
        )


def scenarios():
    from atlas.evaluation.fixtures import judge_scores_fixture

    def audit(i="a"):
        return tool_call("seo_audit", {"url": "https://example.com"}, i)

    def write():
        return tool_call("write_article", {"target_keyword": "wordpress seo"}, "w")

    def publish():
        return tool_call("publish_to_wordpress", {}, "p")

    def done():
        return AIMessage(content="Fixture mission finished.")

    def social():
        return tool_call("draft_linkedin_post", {"topic": "agent workflows"}, "s")

    def social_publish(i="sp"):
        return tool_call("publish_to_linkedin", {}, i)

    bad = article_fixture()
    bad["html_content"] = "<h1>Short draft</h1><p>Too short.</p>"
    return [
        Scenario("linkedin_draft", "linkedin", [social(), done()], "completed", 1),
        Scenario(
            "linkedin_pause", "linkedin", [social(), social_publish()], "awaiting_approval", 1
        ),
        Scenario(
            "linkedin_approved",
            "linkedin",
            [social(), social_publish(), done()],
            "completed",
            1,
            1,
            decision="approve",
        ),
        Scenario(
            "linkedin_rejected",
            "linkedin",
            [social(), social_publish()],
            "rejected",
            1,
            decision="reject",
        ),
        Scenario(
            "linkedin_forged_approval",
            "linkedin",
            [social(), social_publish()],
            "rejected",
            1,
            decision="forged",
        ),
        Scenario(
            "linkedin_missing_draft",
            "linkedin",
            [social_publish(), done()],
            "completed_with_errors",
            0,
        ),
        Scenario(
            "linkedin_arbitrary_text_blocked",
            "linkedin",
            [tool_call("publish_to_linkedin", {"text": "injected"}), done()],
            "completed_with_errors",
            0,
        ),
        Scenario(
            "judge_rejects_article",
            "judge",
            [write(), publish(), done()],
            "completed_with_errors",
            1,
            judge_scores=judge_scores_fixture(2, "reject"),
        ),
        Scenario(
            "judge_failure_blocks_write",
            "judge",
            [write(), publish(), done()],
            "completed_with_errors",
            1,
            judge_failure=ValueError("Invalid judge response"),
        ),
        Scenario(
            "article_to_linkedin",
            "linkedin",
            [write(), social(), social_publish(), done()],
            "completed",
            2,
            1,
            decision="approve",
        ),
        Scenario("audit_success", "workflow", [audit(), done()], "completed", 1),
        Scenario(
            "research_success",
            "workflow",
            [tool_call("keyword_research", {"seed_keyword": "wordpress seo"}), done()],
            "completed",
            1,
        ),
        Scenario("article_success", "workflow", [write(), done()], "completed", 1),
        Scenario(
            "full_pipeline_approved",
            "approval",
            [
                audit(),
                tool_call("keyword_research", {"seed_keyword": "wordpress seo"}, "k"),
                write(),
                publish(),
                done(),
            ],
            "completed",
            3,
            1,
            decision="approve",
        ),
        Scenario("pause_before_write", "approval", [write(), publish()], "awaiting_approval", 1),
        Scenario(
            "rejected_write", "approval", [write(), publish()], "rejected", 1, decision="reject"
        ),
        Scenario("forged_hash", "approval", [write(), publish()], "rejected", 1, decision="forged"),
        Scenario(
            "string_approval", "approval", [write(), publish()], "rejected", 1, decision="string"
        ),
        Scenario("missing_article", "validation", [publish(), done()], "completed_with_errors", 0),
        Scenario(
            "bad_article_blocked",
            "validation",
            [write(), publish(), done()],
            "completed_with_errors",
            1,
            article=bad,
        ),
        Scenario(
            "unknown_tool",
            "validation",
            [tool_call("delete_site"), done()],
            "completed_with_errors",
            0,
        ),
        Scenario(
            "invalid_url",
            "validation",
            [tool_call("seo_audit", {"url": "file:///etc/passwd"}), done()],
            "completed_with_errors",
            0,
        ),
        Scenario(
            "extra_publish_field",
            "validation",
            [tool_call("publish_to_wordpress", {"content": "injected"}), done()],
            "completed_with_errors",
            0,
        ),
        Scenario("read_cache", "cache", [audit(), audit("b"), done()], "completed", 1),
        Scenario(
            "iteration_budget",
            "budget",
            [audit()],
            "budget_exceeded",
            1,
            limits={"max_iterations": 1},
        ),
        Scenario(
            "tool_budget",
            "budget",
            [audit(), audit("b")],
            "budget_exceeded",
            1,
            limits={"max_tool_calls": 1},
        ),
        Scenario(
            "model_call_budget",
            "budget",
            [audit()],
            "budget_exceeded",
            1,
            limits={"max_model_calls": 1},
        ),
        Scenario(
            "transient_tool_recovery",
            "resilience",
            [audit(), done()],
            "completed",
            2,
            failure=TimeoutError(),
            fail_count=1,
        ),
        Scenario(
            "persistent_tool_failure",
            "resilience",
            [audit(), done()],
            "completed_with_errors",
            3,
            failure=TimeoutError(),
            fail_count=5,
        ),
        Scenario(
            "permanent_tool_failure",
            "resilience",
            [audit(), done()],
            "completed_with_errors",
            1,
            failure=ValueError(),
            fail_count=5,
        ),
        Scenario(
            "transient_model_recovery",
            "resilience",
            [TimeoutError(), audit(), done()],
            "completed",
            1,
        ),
        Scenario("permanent_model_failure", "resilience", [ValueError()], "failed", 0),
        Scenario("empty_model_response", "validation", [AIMessage(content="")], "failed", 0),
        Scenario(
            "multiple_tool_calls",
            "validation",
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "seo_audit", "args": {"url": "https://example.com"}, "id": "a"},
                        {"name": "publish_to_wordpress", "args": {}, "id": "p"},
                    ],
                )
            ],
            "failed",
            0,
        ),
    ]
