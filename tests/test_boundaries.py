import json
import socket
from unittest.mock import Mock

import httpx
import pytest
from langchain_core.messages import AIMessage

from atlas import db, llm, network
from atlas.evaluation.fixtures import AUDIT, KEYWORDS, article_fixture
from atlas.harness import Usage, compact_result, transient, usage_scope
from atlas.schemas import AuditAnalysis, HarnessConfig
from atlas.workflow import Services


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "https://user:password@example.com",
        "https://example.com/\nBAD",
        'https://example.com/"x',
        "https://example.com:99999",
        "ftp://example.com",
    ],
)
def test_url_syntax_rejected(url):
    with pytest.raises(ValueError):
        network.validate_url(url, resolve=False)


@pytest.mark.parametrize(
    "address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "192.168.1.1", "0.0.0.0"]
)
def test_non_public_destination_rejected(monkeypatch, address):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", (address, 443))])
    with pytest.raises(ValueError, match="Private"):
        network.validate_url("https://example.com")


def test_local_opt_in(monkeypatch):
    monkeypatch.setenv("ATLAS_ALLOW_PRIVATE_URLS", "true")
    assert network.validate_url("http://localhost:8080") == "http://localhost:8080"


def mock_http(monkeypatch, handler):
    original = httpx.Client
    monkeypatch.setattr(
        network.httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )


def test_redirect_target_is_revalidated(monkeypatch):
    seen = []

    def validate(url):
        seen.append(url)
        if "internal" in url:
            raise ValueError("private address")

    monkeypatch.setattr(network, "validate_url", validate)
    mock_http(monkeypatch, lambda r: httpx.Response(302, headers={"location": "http://internal/"}))
    with pytest.raises(ValueError, match="private"):
        network.safe_get("https://example.com")
    assert seen == ["https://example.com", "http://internal/"]


def test_response_size_and_redirect_limits(monkeypatch):
    monkeypatch.setattr(network, "validate_url", lambda u: u)
    mock_http(monkeypatch, lambda r: httpx.Response(200, content=b"x" * 20))
    with pytest.raises(ValueError, match="exceeds"):
        network.safe_get("https://example.com", max_bytes=10)


def test_http_read_success(monkeypatch):
    monkeypatch.setattr(network, "validate_url", lambda u: u)
    mock_http(monkeypatch, lambda r: httpx.Response(200, text="hello"))
    assert network.safe_get("https://example.com").text == "hello"


def test_redirect_loop_bounded(monkeypatch):
    monkeypatch.setattr(network, "validate_url", lambda u: u)
    mock_http(monkeypatch, lambda r: httpx.Response(302, headers={"location": "/loop"}))
    with pytest.raises(ValueError, match="Too many"):
        network.safe_get("https://example.com")


def test_llm_adapter_configuration(monkeypatch):
    constructor = Mock(return_value="model")
    monkeypatch.setattr(llm, "init_chat_model", constructor)
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    with pytest.raises(RuntimeError, match="GROQ"):
        llm.get_chat_model()
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    assert llm.get_chat_model() == "model"
    assert constructor.call_args.kwargs["max_retries"] == 0
    assert constructor.call_args.kwargs["timeout"] == 60
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    assert llm.get_chat_model() == "model"
    assert constructor.call_args.kwargs["base_url"] == "http://localhost:11434/v1"
    monkeypatch.setenv("LLM_PROVIDER", "invalid")
    with pytest.raises(ValueError):
        llm.get_chat_model()


def test_structured_repair_counts_usage(monkeypatch):
    raw = AIMessage(
        content="fixture", usage_metadata={"input_tokens": 4, "output_tokens": 2, "total_tokens": 6}
    )
    runnable = Mock()
    runnable.invoke.side_effect = [
        {"raw": raw, "parsed": None},
        {"raw": raw, "parsed": AuditAnalysis(issues=[])},
    ]
    model = Mock()
    model.with_structured_output.return_value = runnable
    monkeypatch.setattr(llm, "get_chat_model", lambda: model)
    usage = Usage(HarnessConfig())
    with usage_scope(usage):
        assert llm.structured_response(AuditAnalysis, "Audit").issues == []
    assert usage.model_calls == 2 and usage.input_tokens == 8 and usage.output_tokens == 4
    assert len(runnable.invoke.call_args.args[0]) == 3


def test_structured_repair_exhaustion(monkeypatch):
    model = Mock()
    model.with_structured_output.return_value.invoke.return_value = {"parsed": None}
    monkeypatch.setattr(llm, "get_chat_model", lambda: model)
    with pytest.raises(ValueError, match="two attempts"):
        llm.structured_response(AuditAnalysis, "Audit")
    assert model.with_structured_output.return_value.invoke.call_count == 2


def test_text_response_empty_rejected(monkeypatch):
    model = Mock()
    model.invoke.return_value = AIMessage(content=" ")
    monkeypatch.setattr(llm, "get_chat_model", lambda **k: model)
    with pytest.raises(ValueError, match="no text"):
        llm.text_response("draft")


def test_compaction_preserves_json():
    text = compact_result({"source": '"' * 10000, "data": "private"}, 256)
    assert len(text) <= 256 and json.loads(text)["truncated"]


def test_http_retry_classification():
    request = httpx.Request("GET", "https://example.com")
    for status, retry in [(429, True), (503, True), (401, False), (404, False)]:
        error = httpx.HTTPStatusError(
            "failure", request=request, response=httpx.Response(status, request=request)
        )
        assert transient(error) == retry


def test_all_history_artifacts_roundtrip():
    mission = db.save_mission("Audit and write", "https://example.com")
    audit = db.save_audit(mission, AUDIT["url"], issues=AUDIT["top_issues"], score=75)
    keyword = db.save_keywords(mission, "wordpress seo", KEYWORDS["keywords"], KEYWORDS["clusters"])
    article = db.save_article(mission, **article_fixture())
    log = db.save_publish_log(mission, article, wp_post_id=42, status="draft")
    assert db.fetch_audit(audit)["score"] == 75
    assert db.fetch_keywords(keyword)["seed"] == "wordpress seo"
    assert db.fetch_article(article)["word_count"] > 1200
    assert db.fetch_publish_log(log)["wp_post_id"] == 42
    assert len(db.list_audits(mission)) == len(db.list_keywords(mission)) == 1
    assert len(db.list_articles(mission)) == len(db.list_publish_logs(mission)) == 1
    for fetch in (
        db.fetch_mission,
        db.fetch_audit,
        db.fetch_keywords,
        db.fetch_article,
        db.fetch_publish_log,
    ):
        assert fetch(99999) is None


def test_production_services_persist_results(monkeypatch):
    from atlas.tools import article_writer, auditor, keywords

    monkeypatch.setattr(auditor, "run_audit", lambda **kw: AUDIT)
    monkeypatch.setattr(keywords, "research_keywords", lambda **kw: KEYWORDS)
    monkeypatch.setattr(article_writer, "write_article", lambda **kw: article_fixture())
    services = Services()
    state = {"mission_id": db.save_mission("fixture", "https://example.com")}
    assert services.execute("seo_audit", {"url": "https://example.com"}, state)["score"] == 75
    assert (
        services.execute("keyword_research", {"seed_keyword": "wordpress seo"}, state)["total"] == 1
    )
    assert (
        services.execute("write_article", {"target_keyword": "wordpress seo"}, state)["word_count"]
        > 1200
    )
    assert (
        len(db.list_audits(state["mission_id"])) == len(db.list_articles(state["mission_id"])) == 1
    )


def test_production_publication_destination_locked(monkeypatch):
    monkeypatch.setenv("WP_URL", "https://example.com")
    monkeypatch.setenv("WP_USER", "user")
    monkeypatch.setenv("WP_APP_PASSWORD", "password")
    services = Services()
    assert services.destination() == "https://example.com"
    with pytest.raises(ValueError, match="destination changed"):
        services.publish({"destination": "https://changed.example", "post": {}})
    from atlas.tools.wordpress import WordPressClient

    monkeypatch.setattr(
        WordPressClient, "create_post", lambda self, **kw: {"post_id": 42, "status": "draft"}
    )
    assert services.publish(
        {"destination": "https://example.com", "post": {"title": "a", "content": "b"}}
    )["ok"]


def test_streamlit_initial_render():
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file("../ui/streamlit_app.py").run(timeout=15)
    assert not app.exception
    assert app.button[1].label == "🚀 Run ATLAS"
