"""Orchestrates all SEO data-collection tools and produces a prioritised audit report."""

import json
from typing import Optional

from atlas.llm import structured_response
from atlas.schemas import AuditAnalysis
from atlas.tools.crawler import crawl_url
from atlas.tools.lighthouse import run_lighthouse
from atlas.tools.robots_sitemap import fetch_robots_txt, fetch_sitemap


def run_audit(url: str, mission_id: Optional[int] = None) -> dict:
    """
    Run a full SEO audit on a URL.

    Orchestrates crawl_url → run_lighthouse → fetch_robots_txt → fetch_sitemap,
    then calls the LLM to prioritise the top 10 SEO issues.

    Args:
        url: The page URL to audit.
        mission_id: Optional mission ID for contextual logging.

    Returns:
        Structured dict with score, crawl, lighthouse, robots, sitemap, and top_issues.
    """
    print(f"[Auditor] Crawling {url}...")
    crawl_data = crawl_url(url)

    print("[Auditor] Running Lighthouse...")
    lighthouse_data = run_lighthouse(url)

    print("[Auditor] Fetching robots.txt...")
    robots_data = fetch_robots_txt(url)

    print("[Auditor] Fetching sitemap...")
    sitemap_data = fetch_sitemap(url)

    print("[Auditor] Analysing with LLM...")
    issues = _analyse_with_llm(url, crawl_data, lighthouse_data, robots_data, sitemap_data)

    score = _compute_overall_score(crawl_data, lighthouse_data)

    return {
        "url": url,
        "mission_id": mission_id,
        "score": score,
        "crawl": crawl_data,
        "lighthouse": lighthouse_data,
        "robots": robots_data,
        "sitemap": sitemap_data,
        "top_issues": issues,
    }


def _compute_overall_score(crawl_data: dict, lighthouse_data: dict) -> float | None:
    """
    Compute a 0-100 overall SEO score from crawl and Lighthouse data.

    Averages the Lighthouse SEO + performance scores with an on-page
    heuristic score derived from title, description, H1, and image alt text.
    """
    if not crawl_data.get("ok", True):
        return None

    scores: list[float] = []

    if lighthouse_data.get("ok"):
        lh = lighthouse_data.get("scores") or {}
        if lh.get("seo") is not None:
            scores.append(lh["seo"])
        if lh.get("performance") is not None:
            scores.append(lh["performance"])

    on_page = 100.0
    title = crawl_data.get("title") or {}
    if not (isinstance(title, dict) and title.get("text")):
        on_page -= 20
    meta = crawl_data.get("meta") or {}
    desc = meta.get("description") or {}
    if not (isinstance(desc, dict) and desc.get("text")):
        on_page -= 15
    headings = crawl_data.get("headings") or {}
    if not headings.get("h1"):
        on_page -= 15
    images = crawl_data.get("images") or {}
    missing_alt = images.get("missing_alt", 0)
    if missing_alt > 0:
        on_page -= min(10, missing_alt * 2)

    scores.append(max(0.0, on_page))
    return round(sum(scores) / len(scores)) if scores else 50.0


def _analyse_with_llm(
    url: str,
    crawl_data: dict,
    lighthouse_data: dict,
    robots_data: dict,
    sitemap_data: dict,
) -> list[dict]:
    """
    Call the LLM to identify and rank the top 10 SEO issues.

    Builds a compact summary of audit data to keep prompt size manageable,
    then validates the structured response against the audit issue schema.
    """
    summary = {
        "url": url,
        "title": crawl_data.get("title"),
        "meta_description": (crawl_data.get("meta") or {}).get("description"),
        "h1_tags": (crawl_data.get("headings") or {}).get("h1", []),
        "image_count": (crawl_data.get("images") or {}).get("total", 0),
        "images_missing_alt": (crawl_data.get("images") or {}).get("missing_alt", 0),
        "internal_links": (crawl_data.get("links") or {}).get("counts", {}).get("internal", 0),
        "lighthouse_seo_score": (lighthouse_data.get("scores") or {}).get("seo"),
        "lighthouse_perf_score": (lighthouse_data.get("scores") or {}).get("performance"),
        "lighthouse_opportunities": (lighthouse_data.get("opportunities") or [])[:5],
        "robots_exists": (robots_data or {}).get("exists"),
        "sitemap_total_urls": (sitemap_data or {}).get("total_urls"),
        "structured_data_count": len(crawl_data.get("structured_data") or []),
        "canonical": (crawl_data.get("meta") or {}).get("canonical"),
        "open_graph": crawl_data.get("open_graph"),
    }

    return [
        issue.model_dump()
        for issue in structured_response(
            AuditAnalysis,
            "Identify up to 10 evidence-supported SEO issues in this audit. Do not invent issues "
            "to fill a quota. Rank by impact and give actionable recommendations. Audit data:\n"
            + json.dumps(summary, default=str),
        ).issues
    ]
