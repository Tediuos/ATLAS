"""HTML sanitation and deterministic editorial checks; not a factuality judge."""

import re

import nh3
from selectolax.parser import HTMLParser

from atlas.schemas import Article


def sanitize_html(content: str) -> str:
    return nh3.clean(
        content,
        tags={
            "h1",
            "h2",
            "h3",
            "p",
            "ul",
            "ol",
            "li",
            "strong",
            "em",
            "a",
            "blockquote",
            "br",
            "table",
            "thead",
            "tbody",
            "tr",
            "th",
            "td",
        },
        attributes={"a": {"href", "title"}},
        url_schemes={"https", "http"},
    )


def article_quality(value: dict) -> dict:
    article = Article.model_validate(value)
    tree = HTMLParser(article.html_content)
    text = tree.text(separator=" ", strip=True)
    count = len(text.split())
    keyword = article.target_keyword.casefold()
    h1 = tree.css("h1")
    first = tree.css_first("p")
    checks = {
        "word_count": 1200 <= count <= 1800,
        "one_h1": len(h1) == 1,
        "keyword_in_h1": bool(h1 and keyword in h1[0].text().casefold()),
        "keyword_in_intro": bool(first and keyword in first.text().casefold()),
        "section_count": 4 <= len(tree.css("h2")) <= 8,
        "meta_length": 50 <= len(article.meta_description) <= 165,
        "keyword_in_meta": keyword in article.meta_description.casefold(),
        "no_active_html": not bool(tree.css("script,iframe,object,embed,form"))
        and not bool(re.search(r"\son\w+\s*=|javascript:", article.html_content, re.I)),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "word_count": count,
        "score": round(sum(checks.values()) / len(checks) * 100, 1),
    }
