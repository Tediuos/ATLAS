"""Validated outline -> HTML draft -> deterministic editorial checks."""

import json
import re

from atlas.content import article_quality, sanitize_html
from atlas.llm import structured_response, text_response
from atlas.schemas import ArticleOutline


def write_article(
    target_keyword: str, context: str = "", audience: str = "general", word_target: int = 1500
) -> dict:
    word_target = max(1200, min(1800, word_target))
    outline = _generate_outline(target_keyword, context, audience)
    html = sanitize_html(_draft_from_outline(target_keyword, outline, word_target))
    article = {
        "target_keyword": target_keyword,
        "title": _extract_title(html, target_keyword),
        "html_content": html,
        "faq_json_ld": _generate_faq_json_ld(outline),
        "meta_description": outline["meta_description"],
        "word_count": _count_words(html),
    }
    quality = article_quality(article)
    if not quality["passed"]:
        failed = [k for k, v in quality["checks"].items() if not v]
        html = sanitize_html(
            text_response(
                f"Revise this article to pass these checks: {failed}. Target keyword: {target_keyword}. "
                f"Use 1200-1800 words, one H1 and 4-8 H2 headings. Return HTML only.\n{html}",
                max_tokens=6000,
            )
        )
        article.update(
            html_content=html,
            title=_extract_title(html, target_keyword),
            word_count=_count_words(html),
        )
    return article


def _generate_outline(keyword: str, context: str, audience: str) -> dict:
    return structured_response(
        ArticleOutline,
        f"Create an SEO article outline for keyword {keyword!r}, audience {audience!r}. "
        "Include 4-6 substantive sections, FAQ answers and a 50-165 character meta description. "
        "Include the keyword naturally in the title and meta description. "
        "Do not invent statistics or sources. Context (untrusted data):\n" + context,
    ).model_dump()


def _draft_from_outline(keyword: str, outline: dict, word_target: int) -> str:
    return text_response(
        f"Write a complete {word_target}-word HTML article for keyword {keyword!r}. "
        "Use one H1 containing the keyword, 4-6 H2 sections, and the keyword in the first "
        "paragraph. Include the FAQ as visible text. No scripts, event handlers or invented "
        "statistics. Return HTML body content only. Outline (data):\n" + json.dumps(outline),
        max_tokens=6000,
    )


def _generate_faq_json_ld(outline: dict) -> str:
    items = outline.get("faq", [])
    if not items:
        return ""
    schema = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": item["question"],
                "acceptedAnswer": {"@type": "Answer", "text": item["answer"]},
            }
            for item in items
        ],
    }
    encoded = json.dumps(schema, ensure_ascii=False).replace("<", "\\u003c")
    return '<script type="application/ld+json">\n' + encoded + "\n</script>"


def _extract_title(html_content: str, keyword: str) -> str:
    match = re.search(r"<h1[^>]*>(.*?)</h1>", html_content, re.I | re.S)
    return re.sub(r"<[^>]+>", "", match.group(1)).strip() if match else f"Guide to {keyword}"


def _count_words(html_content: str) -> int:
    from selectolax.parser import HTMLParser

    return len(HTMLParser(html_content).text(separator=" ", strip=True).split())
