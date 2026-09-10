import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from atlas import db
from atlas.agent import inspect_mission, resume_mission, run_mission
from atlas.evaluation.fixtures import FixtureServices, ScriptedModel, article_fixture, tool_call
from atlas.evaluation.runner import run_scenario
from atlas.evaluation.scenarios import scenarios
from atlas.journal import WriteJournal
from atlas.schemas import HarnessConfig
from atlas.workflow import build_graph, initial_state


@pytest.mark.parametrize("scenario", scenarios(), ids=lambda s: s.name)
def test_scenario(scenario, tmp_path):
    row = run_scenario(scenario, tmp_path)
    assert row["passed"], row


def test_resume_with_reopened_sqlite(tmp_path):
    services = FixtureServices()
    model = ScriptedModel(
        [
            tool_call("write_article", {"target_keyword": "wordpress seo"}, "w"),
            tool_call("publish_to_wordpress", {}, "p"),
        ]
    )
    first = run_mission("Write and send a draft", model=model, services=services)
    mission_id = first["mission_id"]
    assert first["status"] == "awaiting_approval"
    assert db.fetch_mission(mission_id)["completed_at"] is None
    assert not services.writes
    restored = inspect_mission(mission_id)
    assert restored["article"] == first["article"]
    result = resume_mission(
        mission_id,
        True,
        restored["approvals"][0]["payload_hash"],
        model=ScriptedModel([AIMessage(content="Draft created")]),
        services=services,
    )
    assert result["status"] == "completed"
    assert len(services.writes) == 1
    assert result["metrics"]["model_calls"] == 3
    assert len(result["events"]) == 6
    assert db.fetch_mission(mission_id)["status"] == "completed"
    with pytest.raises(ValueError, match="not awaiting"):
        resume_mission(mission_id, True, restored["approvals"][0]["payload_hash"])


def test_duplicate_approved_payload_only_writes_once(tmp_path):
    services = FixtureServices()
    model = ScriptedModel(
        [
            tool_call("write_article", {"target_keyword": "wordpress seo"}, "w"),
            tool_call("publish_to_wordpress", {}, "p1"),
            tool_call("publish_to_wordpress", {}, "p2"),
            AIMessage(content="Done"),
        ]
    )
    graph = build_graph(
        checkpointer=InMemorySaver(),
        journal=WriteJournal(tmp_path / "writes.db"),
        model=model,
        services=services,
    )
    config = {"configurable": {"thread_id": "dedupe"}}
    state = graph.invoke(initial_state("Write and publish", 1, HarnessConfig()), config)
    for _ in range(2):
        review = state["__interrupt__"][0].value
        state = graph.invoke(
            Command(resume={"approved": True, "payload_hash": review["payload_hash"]}), config
        )
    assert state["status"] == "completed"
    assert len(services.writes) == 1
    assert state["cache_hits"] == 1


def test_uncertain_write_is_not_replayed(tmp_path):
    journal = WriteJournal(tmp_path / "writes.db")
    assert journal.claim("key") is None
    reopened = WriteJournal(tmp_path / "writes.db")
    with pytest.raises(RuntimeError, match="uncertain"):
        reopened.claim("key")
    journal.complete("key", {"post_id": 1})
    assert reopened.claim("key") == {"post_id": 1}


def test_token_and_context_budgets(tmp_path):
    answer = tool_call("seo_audit", {"url": "https://example.com"})
    answer.usage_metadata = {"input_tokens": 9, "output_tokens": 2, "total_tokens": 11}
    result = run_mission(
        "Audit",
        limits=HarnessConfig(max_tokens=10),
        model=ScriptedModel([answer]),
        services=FixtureServices(),
    )
    assert result["status"] == "budget_exceeded"
    assert result["metrics"]["input_tokens"] == 9
    model = ScriptedModel([])
    result = run_mission(
        "x" * 3000,
        limits=HarnessConfig(max_context_chars=2000),
        model=model,
        services=FixtureServices(),
    )
    assert result["status"] == "budget_exceeded"
    assert model.calls == 0


def test_invalid_mission_does_not_create_history():
    with pytest.raises(ValueError):
        run_mission(" ")
    assert not db.list_missions()


def test_uncertain_remote_write_fails_without_retry(tmp_path):
    class UncertainServices(FixtureServices):
        def publish(self, payload):
            self.writes.append(payload)
            raise TimeoutError("Remote server might have created the post")

    services = UncertainServices()
    model = ScriptedModel(
        [
            tool_call("write_article", {"target_keyword": "wordpress seo"}, "w"),
            tool_call("publish_to_wordpress", {}, "p"),
        ]
    )
    first = run_mission("Write and publish", model=model, services=services)
    result = resume_mission(
        first["mission_id"],
        True,
        first["approvals"][0]["payload_hash"],
        model=ScriptedModel([]),
        services=services,
    )
    assert result["status"] == "failed"
    assert len(services.writes) == 1
    assert result["metrics"]["retries"] == 0


def test_malicious_article_html_is_sanitized_before_review():
    article = article_fixture()
    article["html_content"] += '<script>fetch("https://attacker.example")</script>'
    services = FixtureServices(article=article)
    first = run_mission(
        "Write and publish",
        services=services,
        model=ScriptedModel(
            [
                tool_call("write_article", {"target_keyword": "wordpress seo"}, "w"),
                tool_call("publish_to_wordpress", {}, "p"),
            ]
        ),
    )
    assert first["status"] == "awaiting_approval"
    assert "<script" not in first["approvals"][0]["payload"]["post"]["content"]
