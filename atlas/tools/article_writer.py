"""Two-pass SEO article writer: outline → per-section draft → FAQ JSON-LD."""
import json
import re

from atlas.llm import get_llm_client


def write_article(
    target_keyword: str,
    context: str = "",
    audience: str = "general",
    word_target: int = 1500,
) -> dict:
    """
    Write a full SEO-optimised HTML article using two-pass prompt chaining.

    Pass 1 — generate a structured outline with H2/H3 sections and FAQ items.
    Pass 2 — draft the complete HTML article from the outline.

    The keyword appears in the H1, meta description, and opening paragraph.
    A FAQ JSON-LD block is generated separately for structured data.

    Args:
        target_keyword: Primary keyword to optimise for.
        context: Extra context from audit or keyword research (may be empty).
        audience: Target reader description (e.g. "small business owners").
        word_target: Desired word count clamped to 1200-1800.

    Returns:
        Dict with: target_keyword, title, html_content, faq_json_ld,
                   meta_description, word_count.
    """
    word_target = max(1200, min(1800, word_target))

    print(f"[ArticleWriter] Pass 1 — outline for '{target_keyword}'")
    outline = _generate_outline(target_keyword, context, audience)

    print("[ArticleWriter] Pass 2 — drafting article")
    html_content = _draft_from_outline(target_keyword, outline, word_target)

    faq_json_ld = _generate_faq_json_ld(outline)
    meta_description = _extract_meta_description(target_keyword, outline)
    title = _extract_title(html_content, target_keyword)
    word_count = _count_words(html_content)

    return {
        "target_keyword": target_keyword,
        "title": title,
        "html_content": html_content,
        "faq_json_ld": faq_json_ld,
        "meta_description": meta_description,
        "word_count": word_count,
    }


def _generate_outline(keyword: str, context: str, audience: str) -> dict:
    """
    Generate a structured outline for the article.

    Returns a dict with title, meta_description, intro_hook, sections, faq,
    and conclusion_points. Falls back to a minimal outline on parse failure.
    """
    prompt = (
        "You are an expert SEO content strategist. Create a detailed article outline for:\n\n"
        f"Target Keyword: {keyword}\n"
        f"Audience: {audience}\n"
        f"Additional context: {context or 'None'}\n\n"
        "Requirements:\n"
        f"- H1 title that naturally includes the keyword \"{keyword}\"\n"
        "- 4-6 H2 sections, each with 2-3 H3 subsections\n"
        "- FAQ section with 5 relevant questions and concise answers\n"
        "- Inverted-pyramid structure (most important information first)\n\n"
        "Return a JSON object:\n"
        "{\n"
        '  "title": "H1 with keyword",\n'
        '  "meta_description": "155-160 char description with keyword",\n'
        '  "intro_hook": "2-3 sentence teaser",\n'
        '  "sections": [\n'
        '    {"h2": "Section title", "key_points": ["..."],\n'
        '     "subsections": [{"h3": "Subsection", "key_points": ["..."]}]}\n'
        "  ],\n"
        '  "faq": [{"question": "...", "answer": "2-3 sentence answer"}],\n'
        '  "conclusion_points": ["takeaway 1", "takeaway 2"]\n'
        "}\n\nReturn ONLY the JSON."
    )

    client, model = get_llm_client()
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4,
    )
    content = response.choices[0].message.content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {
            "title": f"Complete Guide to {keyword}",
            "meta_description": f"Learn everything about {keyword} in this comprehensive guide.",
            "intro_hook": f"Discover the essentials of {keyword}.",
            "sections": [],
            "faq": [],
            "conclusion_points": [],
        }


def _draft_from_outline(keyword: str, outline: dict, word_target: int) -> str:
    """
    Draft a complete HTML article from the outline using a single LLM call.

    Returns raw HTML body content (no <html>/<head>/<body> wrappers).
    """
    title = outline.get("title", f"Complete Guide to {keyword}")
    intro_hook = outline.get("intro_hook", "")
    sections_json = json.dumps(outline.get("sections", []), indent=2)
    conclusion_points = json.dumps(outline.get("conclusion_points", []))

    prompt = (
        f"You are an expert SEO content writer. Write a complete HTML article based on this outline.\n\n"
        f'Target keyword: "{keyword}"\n'
        f"Target word count: {word_target} words\n\n"
        f"Title (H1): {title}\n"
        f"Intro hook: {intro_hook}\n"
        f"Sections: {sections_json}\n"
        f"Conclusion points: {conclusion_points}\n\n"
        "Requirements:\n"
        f'- Include "{keyword}" naturally in the first paragraph\n'
        "- Use <h1>, <h2>, <h3>, <p>, <ul>, <li>, <strong> tags\n"
        "- Write naturally — no keyword stuffing\n"
        "- Each H2 section: at least 200 words\n"
        "- Conclude with a clear call-to-action\n"
        f"- Aim for approximately {word_target} words total\n\n"
        "Return ONLY the HTML body content (no <html>, <head>, or <body> tags)."
    )

    client, model = get_llm_client()
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
        max_tokens=4000,
    )
    return response.choices[0].message.content.strip()


def _generate_faq_json_ld(outline: dict) -> str:
    """
    Build a FAQ JSON-LD <script> block from the outline's faq list.

    Returns an empty string if there are no FAQ items.
    """
    faq_items = outline.get("faq", [])
    if not faq_items:
        return ""

    schema = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": item.get("question", ""),
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": item.get("answer", ""),
                },
            }
            for item in faq_items
        ],
    }
    return (
        '<script type="application/ld+json">\n'
        + json.dumps(schema, indent=2, ensure_ascii=False)
        + "\n</script>"
    )


def _extract_meta_description(keyword: str, outline: dict) -> str:
    """Return the meta description from the outline, or generate a fallback."""
    desc = outline.get("meta_description", "")
    if desc and 50 <= len(desc) <= 165:
        return desc
    title = outline.get("title", keyword)
    return f"Discover everything about {keyword}. {title[:100]}. Expert tips and actionable advice."[:160]


def _extract_title(html_content: str, keyword: str) -> str:
    """Extract the H1 text from HTML, falling back to a default title."""
    match = re.search(r"<h1[^>]*>(.*?)</h1>", html_content, re.IGNORECASE | re.DOTALL)
    if match:
        return re.sub(r"<[^>]+>", "", match.group(1)).strip()
    return f"Complete Guide to {keyword}"


def _count_words(html_content: str) -> int:
    """Count words in HTML by stripping all tags first."""
    text = re.sub(r"<[^>]+>", " ", html_content)
    text = re.sub(r"\s+", " ", text).strip()
    return len(text.split()) if text else 0
