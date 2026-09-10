import json
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from atlas.content import article_quality, sanitize_html
from atlas.evaluation.fixtures import AUDIT, article_fixture
from atlas.schemas import ArticleOutline, AuditAnalysis, KeywordClusters
from atlas.seo_report import generate_report
from atlas.tools import (
    article_writer,
    auditor,
    crawler,
    keywords,
    lighthouse,
    robots_sitemap,
    wordpress,
)


def response(body, status=200, url="https://example.com"):
    return httpx.Response(status, content=body, request=httpx.Request("GET", url))


def test_crawler_extracts_fixture(monkeypatch):
    html = """<html lang="fr"><head><title>Test SEO</title><meta name="description" content="Description">
    <meta property="og:title" content="OG title"><meta name="twitter:card" content="summary">
    <link rel="canonical" href="https://example.com"><link rel="alternate" hreflang="en" href="/en">
    <script type="application/ld+json">{"@type":"Article"}</script>
    <script type="application/ld+json">invalid</script></head><body><h1>Title</h1><h2>Section</h2>
    <a href="/inside">Inside</a><a href="https://outside.example/" rel="nofollow">Outside</a>
    <a href="mailto:a@example.com">Email</a><img src="a.jpg" alt="A"><img src="b.jpg">
    </body></html>"""
    monkeypatch.setattr(crawler, "safe_get", lambda *a, **k: response(html))
    data = crawler.crawl_url("https://example.com")
    assert data["ok"] and data["language"] == "fr"
    assert data["title"]["text"] == "Test SEO"
    assert data["meta"]["description"]["text"] == "Description"
    assert data["headings"]["h1"] == ["Title"]
    assert data["images"]["missing_alt"] == 1
    assert data["links"]["counts"] == {"internal": 1, "external": 1, "total": 2}
    assert data["links"]["external"][0]["nofollow"]
    assert data["structured_data"] == [{"@type": "Article"}]
    assert data["open_graph"]["title"] == "OG title"
    assert data["twitter_card"]["card"] == "summary"


@pytest.mark.parametrize("status", [403, 404, 500])
def test_crawler_http_failure(monkeypatch, status):
    monkeypatch.setattr(crawler, "safe_get", lambda *a, **k: response("error", status))
    assert not crawler.crawl_url("https://example.com")["ok"]


def test_crawler_network_failure(monkeypatch):
    monkeypatch.setattr(crawler, "safe_get", Mock(side_effect=httpx.ConnectError("offline")))
    assert not crawler.crawl_url("https://example.com")["ok"]


def test_lighthouse_zero_score_opportunity():
    data = lighthouse._parse_lighthouse_output(
        {
            "categories": {"seo": {"score": 0.9}},
            "audits": {
                "slow": {
                    "score": 0,
                    "title": "Slow resource",
                    "details": {"type": "opportunity", "overallSavingsMs": 500},
                },
                "largest-contentful-paint": {"numericValue": 2400},
            },
        },
        "https://example.com",
        True,
    )
    assert data["scores"]["seo"] == 90
    assert data["metrics"]["lcp_ms"] == 2400
    assert data["opportunities"][0]["score"] == 0


def test_lighthouse_uses_argument_list(monkeypatch):
    monkeypatch.setattr(lighthouse, "validate_url", lambda u: u)
    monkeypatch.setattr(lighthouse.shutil, "which", lambda _: "/usr/bin/lighthouse")

    def run(args, **kwargs):
        assert isinstance(args, list) and kwargs["shell"] is False
        path = next(x.split("=", 1)[1] for x in args if x.startswith("--output-path="))
        from pathlib import Path

        Path(path).write_text('{"categories": {}}', encoding="utf-8")
        return SimpleNamespace(stderr="", returncode=0)

    monkeypatch.setattr(lighthouse.subprocess, "run", run)
    assert lighthouse.run_lighthouse("https://example.com/?a=1&b=2", mobile=False)["ok"]


def test_lighthouse_missing_cli(monkeypatch):
    monkeypatch.setattr(lighthouse, "validate_url", lambda u: u)
    monkeypatch.setattr(lighthouse.shutil, "which", lambda _: None)
    assert not lighthouse.run_lighthouse("https://example.com")["ok"]


def test_robots_groups_and_sitemap(monkeypatch):
    robots = "User-agent: A\nUser-agent: B\nDisallow: /private # comment\nAllow: /public\nCrawl-delay: 2\nSitemap: https://example.com/map.xml"
    monkeypatch.setattr(robots_sitemap, "safe_get", lambda *a, **k: response(robots))
    result = robots_sitemap.fetch_robots_txt("https://example.com/path")
    assert result["user_agents"]["A"] == result["user_agents"]["B"]
    assert result["user_agents"]["A"]["disallow"] == ["/private"]
    assert result["sitemaps_declared"] == ["https://example.com/map.xml"]


def test_sitemap_bounded_and_cyclic(monkeypatch):
    index = "<sitemapindex><sitemap><loc>https://example.com/sitemap.xml</loc></sitemap><sitemap><loc>https://example.com/child.xml</loc></sitemap></sitemapindex>"
    child = (
        "<urlset>"
        + "".join(f"<url><loc>https://example.com/{i}</loc></url>" for i in range(5))
        + "</urlset>"
    )

    def get(url, **kwargs):
        if url.endswith("robots.txt"):
            return response("", 404)
        return response(child if url.endswith("child.xml") else index)

    monkeypatch.setattr(robots_sitemap, "safe_get", get)
    result = robots_sitemap.fetch_sitemap("https://example.com", max_urls=3)
    assert result["total_urls"] == 3 and result["truncated"]
    assert result["sitemaps_fetched"] == 2 and not result["total_is_exact"]


def test_sitemap_rejects_entities(monkeypatch):
    monkeypatch.setattr(robots_sitemap, "fetch_robots_txt", lambda _: {})
    monkeypatch.setattr(
        robots_sitemap,
        "safe_get",
        lambda *a, **k: response(
            '<!DOCTYPE x [<!ENTITY x SYSTEM "file:///etc/passwd">]><urlset>&x;</urlset>'
        ),
    )
    result = robots_sitemap.fetch_sitemap("https://example.com")
    assert not result["ok"] and result["errors"]


def test_audit_score_and_structured_analysis(monkeypatch):
    crawl = {
        "ok": True,
        "title": {"text": "A"},
        "meta": {"description": {"text": "B"}},
        "headings": {"h1": ["A"]},
        "images": {"missing_alt": 0},
    }
    monkeypatch.setattr(auditor, "crawl_url", lambda _: crawl)
    monkeypatch.setattr(
        auditor, "run_lighthouse", lambda _: {"ok": True, "scores": {"seo": 90, "performance": 80}}
    )
    monkeypatch.setattr(auditor, "fetch_robots_txt", lambda _: {"exists": True})
    monkeypatch.setattr(auditor, "fetch_sitemap", lambda _: {"total_urls": 1})
    monkeypatch.setattr(
        auditor, "structured_response", lambda schema, prompt: AuditAnalysis(issues=[])
    )
    assert auditor.run_audit("https://example.com")["score"] == 90
    assert auditor._compute_overall_score({"ok": False}, {}) is None
    assert auditor._compute_overall_score({}, {}) == 50


def test_keywords_only_rank_observed_keywords(monkeypatch):
    payload = {
        "clusters": {
            "guides": {
                "description": "Guides",
                "keywords": [
                    {"keyword": "observed", "intent": "informational", "volume_rank": 6},
                    {"keyword": "invented", "intent": "commercial", "volume_rank": 10},
                ],
            }
        }
    }
    monkeypatch.setattr(keywords, "structured_response", lambda *a: KeywordClusters(**payload))
    clusters = keywords._cluster_with_llm("seed", ["observed", "missing"])
    ranked = keywords._rank_keywords(["observed", "missing"], clusters)
    assert {r["keyword"] for r in ranked} == {"observed", "missing"}
    assert ranked[0]["keyword"] == "observed"
    assert keywords._cluster_with_llm("seed", []) == {}


def test_keyword_research_is_deterministic(monkeypatch):
    monkeypatch.setattr(keywords, "_fetch_google_autocomplete", lambda *a: ["c", "a", "b"])
    monkeypatch.setattr(keywords, "_cluster_with_llm", lambda *a: {})
    result = keywords.research_keywords("seed", max_suggestions=2)
    assert [r["keyword"] for r in result["keywords"]] == ["a", "b"]


def test_article_generation_and_quality(monkeypatch):
    article = article_fixture()
    outline = {
        "title": article["title"],
        "meta_description": article["meta_description"],
        "intro_hook": "Intro",
        "sections": [{"h2": str(i), "key_points": ["Point"]} for i in range(4)],
        "faq": [{"question": "What?", "answer": "Answer"}],
        "conclusion_points": ["Take action"],
    }
    monkeypatch.setattr(article_writer, "structured_response", lambda *a: ArticleOutline(**outline))
    monkeypatch.setattr(article_writer, "text_response", lambda *a, **k: article["html_content"])
    result = article_writer.write_article("wordpress seo")
    assert article_quality(result)["passed"]
    assert '"@type": "FAQPage"' in result["faq_json_ld"]


def test_article_repair_once(monkeypatch):
    article = article_fixture()
    monkeypatch.setattr(
        article_writer,
        "_generate_outline",
        lambda *a: {"meta_description": article["meta_description"]},
    )
    monkeypatch.setattr(article_writer, "_draft_from_outline", lambda *a: "<p>Short</p>")
    repair = Mock(return_value=article["html_content"])
    monkeypatch.setattr(article_writer, "text_response", repair)
    assert article_quality(article_writer.write_article("wordpress seo"))["passed"]
    assert repair.call_count == 1


@pytest.mark.parametrize(
    "html",
    [
        "<script>alert(1)</script><p>Text</p>",
        "<img src=x onerror=alert(1)>",
        '<a href="javascript:alert(1)">Click</a>',
        '<iframe src="/bad"></iframe>',
    ],
)
def test_sanitize_active_html(html):
    cleaned = sanitize_html(html)
    assert "<script" not in cleaned and "onerror=" not in cleaned
    assert "javascript:" not in cleaned and "<iframe" not in cleaned


def test_faq_script_cannot_break_out():
    result = article_writer._generate_faq_json_ld(
        {"faq": [{"question": "</script><script>alert(1)", "answer": "ok"}]}
    )
    assert result.count("</script>") == 1
    assert "\\u003c/script>" in result


def test_report_escapes_model_and_website_content(tmp_path):
    article = article_fixture()
    article.update(title="<script>alert(1)</script>", html_content='<img onerror="alert(1)">')
    html = generate_report(audit=AUDIT, article=article, output_path=str(tmp_path / "report.html"))
    assert "<script>alert(1)</script>" not in html and "<img onerror=" not in html
    assert "&lt;script&gt;" in html and "75/100" in html
    assert (tmp_path / "report.html").exists()


def test_wordpress_post_not_retried(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("ambiguous remote result")

    original = httpx.Client
    monkeypatch.setattr(
        wordpress.httpx,
        "Client",
        lambda **kw: original(transport=httpx.MockTransport(handler), **kw),
    )
    wp = wordpress.WordPressClient("https://example.com", "user", "password", max_retries=3)
    with pytest.raises(RuntimeError, match="1 attempts"):
        wp.create_post("Title", "Content")
    assert len(calls) == 1


def test_wordpress_read_retries_then_succeeds(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503 if len(calls) == 1 else 200, json={"id": 1})

    original = httpx.Client
    monkeypatch.setattr(
        wordpress.httpx,
        "Client",
        lambda **kw: original(transport=httpx.MockTransport(handler), **kw),
    )
    monkeypatch.setattr(wordpress.time, "sleep", lambda _: None)
    assert wordpress.WordPressClient("https://example.com", "user", "pw").get_post(1)["id"] == 1
    assert len(calls) == 2


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_wordpress_permanent_error_not_retried(monkeypatch, status):
    count = []

    def handler(request):
        count.append(1)
        return httpx.Response(status, text="Failure")

    original = httpx.Client
    monkeypatch.setattr(
        wordpress.httpx,
        "Client",
        lambda **kw: original(transport=httpx.MockTransport(handler), **kw),
    )
    with pytest.raises(RuntimeError):
        wordpress.WordPressClient("https://example.com", "user", "pw").get_post(1)
    assert len(count) == 1


def test_wordpress_success_payload(monkeypatch):
    def handler(request):
        payload = json.loads(request.content)
        assert payload["status"] == "draft" and payload["title"] == "Title"
        assert payload["excerpt"] == "Description" and "meta" not in payload
        assert request.headers["Authorization"].startswith("Basic ")
        return httpx.Response(
            201, json={"id": 9, "title": {"rendered": "Title"}, "status": "draft"}
        )

    original = httpx.Client
    monkeypatch.setattr(
        wordpress.httpx,
        "Client",
        lambda **kw: original(transport=httpx.MockTransport(handler), **kw),
    )
    assert (
        wordpress.WordPressClient("https://example.com", "user", "pw").create_post(
            "Title", "Body", meta_description="Description"
        )["post_id"]
        == 9
    )
